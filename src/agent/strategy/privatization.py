"""私有化：把政府持有的工业建筑卖给私人，养大实业家。

大清 1.13 攻略：学校法（教会 / 公立）只有实业家支持；大清实业家开局边缘化（<1%），
儒生没有支持教会学校的特质。私有化让资本家持股、提高实业家影响力，等他们到 ~5% 再入阁推公立学校。
只动已建成、政府持有、可私有化的工业建筑；每月最多 2 个。
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
            if key in keys and row.levels > 0 and row.can_privatize:
                pool.append((s, key, row))
    pool.sort(key=lambda t: (t[2].profitability or 0.0, t[2].levels), reverse=True)
    out: list[Decision] = []
    for s, key, row in pool[: int(spec.get("max_per_month", 2))]:
        out.append(Decision("privatize", {"state": s.id, "building": key},
                            f"私有化（{s.name} {key}，利润率 {row.profitability or 0:.0f}%，"
                            f"{row.levels} 级）", score=1e5))
    return out
