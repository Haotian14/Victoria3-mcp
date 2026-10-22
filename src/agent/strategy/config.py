"""策略参数（data/strategy.json）与决策的统一表示。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


@lru_cache(maxsize=1)
def cfg() -> dict[str, Any]:
    with open(os.path.join(DATA, "strategy.json"), encoding="utf-8") as f:
        return json.load(f)


def profile_for_tag(tag: str) -> dict[str, Any]:
    """国家专属策略：country_profiles 以游戏 tag（如 CHI）为键。没有就返回空，走通用规则。"""
    return (cfg().get("country_profiles") or {}).get(tag or "", {})


def profile(snap: Any) -> dict[str, Any]:
    tag = str((getattr(snap, "country", {}) or {}).get("tag") or "")
    return profile_for_tag(tag)


def tech_priority(snap: Any) -> list[str]:
    return list(profile(snap).get("tech_priority") or cfg()["tech_priority"])


def law_route(snap: Any) -> list[list[str]]:
    return [list(x) for x in (profile(snap).get("law_route") or cfg()["law_route"])]


@dataclass
class Decision:
    """一个要执行的动作。kind 对应 actions.Actions 的方法名，args 是它的参数（快照另传）。"""
    kind: str                       # set_tax / research / enact_law / build / set_pm
    args: dict[str, Any] = field(default_factory=dict)
    why: str = ""
    score: float = 0.0

    def __str__(self) -> str:
        args = " ".join(f"{k}={v}" for k, v in self.args.items())
        return f"{self.kind} {args} — {self.why}"
