"""读存档（*.v3）。

文件结构（Jomini 通用）：第一行 `SAV...` 头，之后要么直接是 gamestate 文本，
要么是一个 zip（内含 gamestate、meta）。gamestate 有两种编码：

- 文本：与 common/ 定义文件同一套语法，pdx.parse 直接能读；
- 二进制：键是 16 位 token 号，token → 名字的对照表游戏不公开。

**只支持文本存档。** 以 `-debug_mode` 启动游戏时存档写成文本（铁人模式除外），
第二阶段的动作执行本来也要求 debug_mode。遇到二进制存档直接报错说明原因，不猜。
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from typing import Any

from agent import pdx


class SaveFormatError(ValueError):
    pass


@dataclass
class RawSave:
    header: str
    gamestate: str
    meta: str | None


def read_raw(path: str) -> RawSave:
    with open(path, "rb") as f:
        data = f.read()
    if not data.startswith(b"SAV"):
        raise SaveFormatError(f"{path} 不是 Victoria 3 存档（缺少 SAV 头）")
    nl = data.find(b"\n")
    header = data[:nl].decode("ascii", errors="replace").strip()
    body = data[nl + 1:]

    if _looks_zipped(data):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = z.namelist()
            if "gamestate" not in names:
                raise SaveFormatError(f"存档 zip 里没有 gamestate（只有 {names}）")
            gs = z.read("gamestate")
            meta = z.read("meta") if "meta" in names else None
        return RawSave(header, _text(gs, path), _text(meta, path) if meta else None)
    return RawSave(header, _text(body, path), None)


def _looks_zipped(data: bytes) -> bool:
    # meta 可能写在 zip 之前，所以看文件尾的 zip 中央目录结束标记
    return b"PK\x05\x06" in data[-65_536:]


def _text(b: bytes, path: str) -> str:
    if _is_binary(b):
        raise SaveFormatError(
            f"{path} 是二进制存档，无法解析。请用 -debug_mode 启动游戏并重新存档"
            "（非铁人模式），存档就会写成文本。"
        )
    return b.decode("utf-8", errors="replace")


def _is_binary(b: bytes) -> bool:
    head = b[:4096]
    if not head:
        return False
    # 文本存档开头是 `meta_data={` / `date=` 之类的 ASCII；二进制满是 0x00 与控制字节
    ctrl = sum(1 for c in head if c < 9 or 13 < c < 32)
    return ctrl > len(head) // 20


def peek_meta(path: str, size: int = 8192) -> dict[str, Any]:
    """只读文件头的 meta_data（日期、国家名），不解析整个存档。文本存档的 meta_data 在最前面。"""
    with open(path, "rb") as f:
        head = f.read(size).decode("utf-8", errors="replace")
    out: dict[str, Any] = {}
    for key in ("game_date", "name", "version", "rank"):
        m = re.search(rf'^\s*{key}="?([^"\n]+)"?', head, re.M)
        if m:
            out[key] = m.group(1)
    return out


def load(path: str) -> dict[str, Any]:
    """整个 gamestate 转成 dict。大存档较慢（纯 Python 分词）。"""
    raw = read_raw(path)
    return pdx.to_obj(pdx.parse(raw.gamestate))
