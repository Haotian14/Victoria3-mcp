"""外交：提议回复与改善关系。

大清 1836 的核心外交目标是别被孤立：鸦片危机已经默认避战，接下来对俄 / 法 / 普改善关系，
等它们愿意给保障独立 / 防御同盟（提议自动接受）。最后通牒、割让、赔款、投资权、治外法权一律拒绝；
外交博弈里的“拉拢”（sway）也拒绝，避免被拖进别人的战争。
"""

from __future__ import annotations

from typing import Any

from agent.strategy.config import profile

# 1.13 简中实际名称：defensive_pact=共同防御条约、guarantee=保证独立、offer_embassy=建立大使馆、
# trade_privilege=贸易特权；旧关键词匹配不上会把它们静默拒绝（承认路线靠使馆 +1/月）。
DEFAULT_GOOD = ("共同防御条约", "防御同盟", "同盟", "保证独立", "保障独立", "保独", "建立大使馆", "使馆",
                "贸易特权", "贸易协定", "改善关系", "和平", "停战", "白和")
PROTECTIVE = ("共同防御条约", "防御同盟", "同盟", "保证独立", "保障独立", "保独")
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
    if any(x in text for x in PROTECTIVE):
        # 方向盲时会误把大清当保障国/盟友，被拖入别人的战争。
        # proposals() 目前只有 name/actor/kind，方向未知时宁可不签。
        if proposal.get("direction") not in ("incoming", "target", "received"):
            return False
    return any(x in text for x in good)


def improve_targets(snap: Any = None) -> list[str]:
    spec = profile(snap).get("diplomacy") or {}
    return list(spec.get("improve_relations") or ["RUS", "FRA", "PRU"])


def match_action(act: dict[str, Any], keywords: Any) -> bool:
    """外交行动匹配：action key 或中文名包含任一关键词。"""
    text = f"{act.get('action', '')} {act.get('name', '')}".lower()
    return any(str(k).lower() in text for k in (keywords or ()))
