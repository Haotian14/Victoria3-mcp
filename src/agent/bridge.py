"""游戏内桥接层（V3Bridge，127.0.0.1:8766）的 HTTP 客户端。

桥接层把请求放到游戏主线程执行，三类能力：
- console(cmd)            控制台命令（debug_mode 下可用）
- read / read_many        按界面表达式求值，"[GetMetaPlayer.GetPlayedOrObservedCountry.GetGDP|2]"
- exec                    执行语句，与界面 onclick 同一条路径（玩家动作）
- rows                    界面列表（datamodel）逐项求值
- path=[(列表, 下标), ...] 逐层取列表项作为上下文，在某一项上读或执行

游戏侧失败（表达式不合法、动作不可用）是 HTTP 200 + ok:false；连不上 / 协议错误才抛 BridgeError。
"""

from __future__ import annotations

import os
import re
from typing import Any

import httpx

BRIDGE_URL = os.environ.get("V3MCP_URL", "http://127.0.0.1:8766").rstrip("/")

# 读超时要大于桥接层等主线程的上限（60 秒）：游戏加载存档时主线程会卡很久
_TIMEOUT = httpx.Timeout(connect=5.0, read=90.0, write=10.0, pool=5.0)

SEP = "\x1f"                    # read_many / rows 的字段分隔符：表达式里不会出现
FIELD_ERROR = "\x01"            # rows 里单个字段求值失败时以它开头

PLAYER = "GetMetaPlayer.GetPlayedOrObservedCountry"     # 只读路径
PLAYER_MUT = "AccessMetaPlayer.AccessPlayedOrObservedCountry"  # Access* 列表要求非 const

Path = list[tuple[str, int]]


class BridgeError(RuntimeError):
    """桥接层不可达或返回了协议级错误。"""


class GameError(RuntimeError):
    """游戏侧拒绝：表达式不合法、动作不可用、求值失败。"""


# 界面文本里的格式标记：\x15tooltippable_name \x15tooltip:...,...,Tooltip 名字\x15!\x15!
_MARKUP_TOOLTIP = re.compile(r"\x15tooltippable(?:_name)? \x15tooltip:\S+ ")
_MARKUP_REST = re.compile(r"\x15!|\x15[A-Za-z_]+[ ;]?|#[A-Za-z_]+ |#!|@[a-z_]+!")
# 条件说明里的内联提示「:dw_123,xxx,DATA_..._TOOLTIP,XxxTooltip 名字」→「名字」；图标前缀「simple_box!」「CHI156!」
_INLINE_TOOLTIP = re.compile(r":dw_\d+,[^,]*,[A-Z_]+,[A-Za-z]+Tooltip ")
_ICON_PREFIX = re.compile(r"\b[A-Za-z_]+\d*!(?=\S)")


def plain(text: str) -> str:
    """去掉界面格式标记，只留可读文字；多行条件用「；」连起来。"""
    t = _MARKUP_TOOLTIP.sub("", text)
    t = _INLINE_TOOLTIP.sub("", t)
    t = _MARKUP_REST.sub("", t)
    t = _ICON_PREFIX.sub("", t)
    return re.sub(r"\s*\n\s*", "；", t).strip("；").strip()


def number(text: str) -> float | None:
    """把 "1,234.5" / "-12.3%" / "12K" 一类的数字文本转成 float；不是数字返回 None。"""
    t = plain(text).replace(",", "").replace("%", "").strip()
    mult = 1.0
    if t[-1:] in ("K", "M"):
        mult = 1e3 if t[-1] == "K" else 1e6
        t = t[:-1]
    try:
        return float(t) * mult
    except ValueError:
        return None


class Bridge:
    def __init__(self, url: str = BRIDGE_URL) -> None:
        self.url = url
        self._client = httpx.Client(timeout=_TIMEOUT, trust_env=False)   # 桥接层在本机，不走系统代理

    def _request(self, method: str, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            r = self._client.request(method, f"{self.url}{path}", params=params)
        except httpx.ConnectError as exc:
            raise BridgeError(f"连不上桥接层 {self.url}：游戏是否已用 scripts/launch.ps1 启动？（{exc}）") from exc
        except httpx.ReadTimeout as exc:
            raise BridgeError(f"桥接层超时（{path}）。动作可能已下发，先读一次状态再决定，不要重发。") from exc
        try:
            payload = r.json()
        except ValueError as exc:
            raise BridgeError(f"桥接层返回的不是 JSON（HTTP {r.status_code}）：{r.text[:200]}") from exc
        if r.status_code >= 400:
            raise BridgeError(f"桥接层拒绝了请求（HTTP {r.status_code}）：{payload}")
        return payload

    # ------------------------------------------------------------ 基础
    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def alive(self) -> bool:
        try:
            return bool(self.health().get("ok"))
        except BridgeError:
            return False

    def console(self, cmd: str) -> dict[str, Any]:
        return self._request("POST", "/console", {"cmd": cmd})

    # ------------------------------------------------------------ 数据系统
    # path：上下文路径 [(列表语句, 下标), ...]，逐层取列表项作为后续表达式的上下文，
    # 如 [(f"{PLAYER_MUT}.AccessStates", 3)] 之后就能写 "State.GetName"。

    @staticmethod
    def _path(path: Path | None) -> dict[str, Any]:
        q: dict[str, Any] = {}
        for k, (lst, idx) in enumerate(path or []):
            q[f"p{k}"] = lst
            q[f"i{k}"] = idx
        return q

    def read(self, text: str, path: Path | None = None) -> str:
        """一段界面文本（可含多个 [..]）的求值结果，原样返回。失败抛 GameError。"""
        r = self._request("POST", "/data/read", {"text": text, **self._path(path)})
        if not r.get("ok"):
            raise GameError(f"{text}：{r.get('output')}")
        return r["output"]

    def read_many(self, exprs: list[str], path: Path | None = None) -> list[str | None]:
        """一次往返求多个表达式（不带方括号）。整批失败时逐个重试，求不出的位置给 None。
        带 path 时每段只能有一个需要上下文的表达式，所以逐个求。"""
        if not exprs:
            return []
        if not path:
            try:
                parts = self.read(SEP.join(f"[{e}]" for e in exprs)).split(SEP)
                if len(parts) == len(exprs):
                    return parts
            except GameError:
                pass
        out: list[str | None] = []
        for e in exprs:
            try:
                out.append(self.read(f"[{e}]", path))
            except GameError:
                out.append(None)
        return out

    def exec(self, stmt: str, path: Path | None = None) -> None:
        """执行语句（不带方括号），如 "Execute(Building.QueueConstruction)"。失败抛 GameError。"""
        r = self._request("POST", "/data/exec", {"stmt": stmt, **self._path(path)})
        if not r.get("ok"):
            raise GameError(f"{stmt}：{r.get('output')}")

    def rows(self, list_stmt: str, fields: list[str], path: Path | None = None, limit: int = 0) -> list[list[str]]:
        """界面列表逐项求值。fields 每项是不带方括号的表达式，如 "Technology.GetName"。
        单个字段失败时该格以 FIELD_ERROR 开头，不影响其他格。"""
        r = self._request("POST", "/data/list", {"list": list_stmt, "fields": SEP.join(f"[{f}]" for f in fields),
                                                 "limit": limit, **self._path(path)})
        if not r.get("ok"):
            raise GameError(f"{list_stmt}：{r.get('output')}")
        return r["output"]
