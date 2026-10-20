"""游戏目录与用户目录（存档、日志、mod）。

一律可用环境变量覆盖：
- V3MCP_GAME_DIR  游戏安装目录（含 game/、binaries/）
- V3MCP_USER_DIR  用户目录（Documents/Paradox Interactive/Victoria 3）
否则从 Steam 的 libraryfolders.vdf 找。
"""

from __future__ import annotations

import glob
import os
import re
from functools import lru_cache

_STEAM_ROOTS = [
    r"C:\Program Files (x86)\Steam",
    r"C:\Program Files\Steam",
]


@lru_cache(maxsize=1)
def game_dir() -> str:
    env = os.environ.get("V3MCP_GAME_DIR")
    if env:
        return env
    for lib in _steam_libraries():
        d = os.path.join(lib, "steamapps", "common", "Victoria 3")
        if os.path.isfile(os.path.join(d, "binaries", "victoria3.exe")):
            return d
    raise FileNotFoundError("找不到 Victoria 3 安装目录，请设置 V3MCP_GAME_DIR")


def _steam_libraries() -> list[str]:
    libs: list[str] = []
    for root in _STEAM_ROOTS:
        vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
        if not os.path.isfile(vdf):
            continue
        libs.append(root)
        with open(vdf, encoding="utf-8", errors="replace") as f:
            for m in re.finditer(r'"path"\s+"([^"]+)"', f.read()):
                libs.append(m.group(1).replace("\\\\", "\\"))
    return list(dict.fromkeys(libs))


def common_dir() -> str:
    return os.path.join(game_dir(), "game", "common")


def localization_dir(lang: str) -> str:
    return os.path.join(game_dir(), "game", "localization", lang)


@lru_cache(maxsize=1)
def user_dir() -> str:
    env = os.environ.get("V3MCP_USER_DIR")
    if env:
        return env
    docs = os.path.join(os.path.expanduser("~"), "Documents")
    return os.path.join(docs, "Paradox Interactive", "Victoria 3")


def save_dir() -> str:
    return os.path.join(user_dir(), "save games")


def latest_save() -> str | None:
    saves = glob.glob(os.path.join(save_dir(), "*.v3"))
    return max(saves, key=os.path.getmtime) if saves else None
