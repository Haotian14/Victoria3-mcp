"""游戏内桥接层（V3Bridge，127.0.0.1:8766）的 HTTP 客户端。

桥接层把请求放到游戏主线程执行，三类能力：
- console(cmd)            控制台命令（debug_mode 下可用）
- read / read_many        按界面表达式求值，"[GetMetaPlayer.GetPlayedOrObservedCountry.GetGDP|2]"
- exec                    执行语句，与界面 onclick 同一条路径（玩家动作）
- rows / exec_on          界面列表（datamodel）逐项求值、在某一项上执行

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


class BridgeError(RuntimeError):
    """桥接层不可达或返回了协议级错误。"""


class GameError(RuntimeError):
    """游戏侧拒绝：表达式不合法、动作不可用、求值失败。"""


# 界面文本里的格式标记：\x15tooltippable_name \x15tooltip:...,...,Tooltip 名字\x15!\x15!
_MARKUP_TOOLTIP = re.compile(r"\x15tooltippable(?:_name)? \x15tooltip:\S+ ")
_MARKUP_REST = re.compile(r"\x15!|\x15[A-Za-z_]+[ ;]?|#[A-Za-z_]+ |#!|@[a-z_]+!")


def plain(text: str) -> str:
    """去掉界面格式标记，只留可读文字。"""
    t = _MARKUP_TOOLTIP.sub("", text)
    t = _MARKUP_REST.sub("", t)
    return t.strip()


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
    def read(self, text: str) -> str:
        """一段界面文本（可含多个 [..]）的求值结果，原样返回。失败抛 GameError。"""
        r = self._request("POST", "/data/read", {"text": text})
        if not r.get("ok"):
            raise GameError(f"{text}：{r.get('output')}")
        return r["output"]

    def read_many(self, exprs: list[str]) -> list[str]:
        """一次往返求多个表达式（不带方括号）。任一失败整批失败 —— 调用方应只放确定可求值的。"""
        if not exprs:
            return []
        out = self.read(SEP.join(f"[{e}]" for e in exprs))
        parts = out.split(SEP)
        if len(parts) != len(exprs):
            raise GameError(f"read_many 结果个数不符：{len(parts)} != {len(exprs)}")
        return parts

    def exec(self, stmt: str) -> None:
        """执行语句（不带方括号），如 "Execute(GetPlayer.SetTaxLevelHigh)"。失败抛 GameError。"""
        r = self._request("POST", "/data/exec", {"stmt": stmt})
        if not r.get("ok"):
            raise GameError(f"{stmt}：{r.get('output')}")

    def rows(self, list_stmt: str, fields: list[str], limit: int = 0) -> list[list[str]]:
        """界面列表逐项求值。fields 每项是一段带一个 [..] 的文本，如 "[Technology.GetName]"。
        单个字段失败时该格以 FIELD_ERROR 开头，不影响其他格。"""
        r = self._request("POST", "/data/list", {"list": list_stmt, "fields": SEP.join(fields), "limit": limit})
        if not r.get("ok"):
            raise GameError(f"{list_stmt}：{r.get('output')}")
        return r["output"]

    def exec_on(self, list_stmt: str, index: int, stmt: str, check: str = "", expect: str = "") -> None:
        """在列表第 index 项的上下文里执行 stmt。给了 check 时先核对该项 check 文本等于 expect。"""
        r = self._request("POST", "/data/list_exec",
                          {"list": list_stmt, "index": index, "stmt": stmt, "check": check, "expect": expect})
        if not r.get("ok"):
            raise GameError(f"{list_stmt}[{index}] {stmt}：{r.get('output')}")
