"""私有化：把政府持有的工业建筑卖给私人，养大实业家。

大清 1.13 攻略：私有化让资本家持股、提高实业家影响力。但 1.13.11 的 `CanBePrivatized`
只是“私有化开关当前是否打开”，不是资格；资格要看 `IsValid(TogglePrivatization)`。
所以只对「有资格、开关未开、实际现金流为正」的建筑提案：重复提案已开的建筑会把它关掉，
负利润建筑即使打开开关也没有买家。每月最多 2 个。
"""

from __future__ import annotations

from agent.observe import Snapshot
from agent.strategy.config import Decision, profile

DEFAULT_KEYS = (
    "building_textile_mill", "building_furniture_manufactory", "building_glassworks",
    "building_tooling_workshop", "building_paper_mill", "building_food_industry",
    "building_arms_industry", "building_chemical_industry", "building_steel_mill",
)


def candidates(snap: Snapshot) -> list[Decision]:
    spec = profile(snap).get("privatize") or {}
    if not spec:
        return []
    keys = set(spec.get("buildings") or DEFAULT_KEYS)
    pool = []
    for s in snap.states:
        if not s.incorporated:
            continue
        for key, row in s.buildings.items():
            if (key in keys and row.levels > 0 and row.can_toggle_privatization
                    and not row.can_privatize and row.profit > 0):
                pool.append((s, key, row))
    pool.sort(key=lambda t: (t[2].profit / max(t[2].levels, 1), t[2].levels), reverse=True)
    out: list[Decision] = []
    for s, key, row in pool[: int(spec.get("max_per_month", 2))]:
        out.append(Decision("privatize", {"state": s.id, "building": key},
                            f"私有化（{s.name} {key}，实际周利润 {row.profit:,.0f}，"
                            f"{row.levels} 级）", score=1e5))
    return out
