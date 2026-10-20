"""静态数据：游戏本体抽出的商品 / 建筑 / 生产方式 / 科技 / 法律定义。

数据文件由 tools/extract_gamedata.py 生成，见 data/。键一律是游戏内部 id
（`building_food_industry`、`pm_bakery`、`grain`），与存档同源。
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any

DATA = os.path.join(os.path.dirname(__file__), "data")

TABLES = ("goods", "buildings", "production_methods", "production_method_groups",
          "technologies", "laws", "law_groups")


def _load(name: str) -> dict[str, Any]:
    with open(os.path.join(DATA, f"{name}.json"), encoding="utf-8") as f:
        return json.load(f)


class GameData:
    def __init__(self) -> None:
        loaded = {name: _load(name) for name in TABLES}
        self.version: str | None = loaded["goods"].get("game_version")
        self.goods: dict[str, dict] = loaded["goods"]["goods"]
        self.buildings: dict[str, dict] = loaded["buildings"]["buildings"]
        self.pms: dict[str, dict] = loaded["production_methods"]["production_methods"]
        self.pmgs: dict[str, dict] = loaded["production_method_groups"]["production_method_groups"]
        self.techs: dict[str, dict] = loaded["technologies"]["technologies"]
        self.laws: dict[str, dict] = loaded["laws"]["laws"]
        self.law_groups: dict[str, dict] = loaded["law_groups"]["law_groups"]

    def table(self, kind: str) -> dict[str, dict]:
        return {
            "goods": self.goods, "buildings": self.buildings, "production_methods": self.pms,
            "production_method_groups": self.pmgs, "technologies": self.techs,
            "laws": self.laws, "law_groups": self.law_groups,
        }[kind]

    def name(self, kind: str, key: str, lang: str = "zh") -> str:
        return (self.table(kind).get(key) or {}).get("name", {}).get(lang, key)

    def base_prices(self) -> dict[str, float]:
        return {k: float(v["cost"]) for k, v in self.goods.items() if v.get("cost") is not None}

    def tech_closure(self, techs: set[str]) -> set[str]:
        """补上前置：存档只列已研究的，但这里也接受手写的「目标科技」集合。"""
        out, stack = set(), list(techs)
        while stack:
            t = stack.pop()
            if t in out:
                continue
            out.add(t)
            stack.extend((self.techs.get(t) or {}).get("requires", []))
        return out

    def search(self, text: str, limit: int = 20) -> list[dict[str, str]]:
        """按 id 或中英文名模糊查找，跨所有表。"""
        text = text.lower()
        hits = []
        for kind in TABLES:
            for key, v in self.table(kind).items():
                names = v.get("name") or {}
                if text in key.lower() or any(text in n.lower() for n in names.values()):
                    hits.append({"kind": kind, "id": key, "zh": names.get("zh", key),
                                 "en": names.get("en", key)})
                    if len(hits) >= limit:
                        return hits
        return hits


@lru_cache(maxsize=1)
def get() -> GameData:
    return GameData()
