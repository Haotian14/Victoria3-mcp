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
