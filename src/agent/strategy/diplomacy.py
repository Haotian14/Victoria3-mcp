"""外交：提议回复与改善关系。

大清 1836 的核心外交目标是别被孤立：鸦片危机已经默认避战，接下来对俄 / 法 / 普改善关系，
等它们愿意给保障独立 / 防御同盟（提议自动接受）。最后通牒、割让、赔款、投资权、治外法权一律拒绝；
外交博弈里的“拉拢”（sway）也拒绝，避免被拖进别人的战争。
"""

from __future__ import annotations

from typing import Any

from agent.strategy.config import profile

DEFAULT_GOOD = ("防御同盟", "同盟", "保障独立", "保独", "贸易协定", "改善关系", "和平", "停战", "白和")
DEFAULT_BAD = ("要求", "最后通牒", "割让", "赔款", "宣战", "战争", "屈服", "投降",
               "义务", "投资权", "治外法权", "条约港")


def accept_proposal(proposal: dict[str, Any], snap: Any = None) -> bool:
    """条约 / 外交行动提议：只接受关键词明确有利的；要挟与拉拢一律拒绝。"""
    if proposal.get("kind") in ("demand", "sway"):
        return False
    spec = profile(snap).get("diplomacy") or {}
    bad = tuple(spec.get("reject_keywords") or DEFAULT_BAD)
    good = tuple(spec.get("accept_keywords") or DEFAULT_GOOD)
    text = f"{proposal.get('name', '')} {proposal.get('actor', '')}"
    if any(x in text for x in bad):
        return False
    return any(x in text for x in good)


def improve_targets(snap: Any = None) -> list[str]:
    spec = profile(snap).get("diplomacy") or {}
    return list(spec.get("improve_relations") or ["RUS", "FRA", "PRU"])
