"""补贴关键工业：先止损保就业，等盈利后取消补贴，让私有化能接手（养大实业家）。

大清 1.13 攻略链：学校法只有实业家支持 → 实业家需要持有盈利的工厂 → 亏损厂没人买；
先补贴纺织 / 家具 / 玻璃 / 工具 / 造纸 / 食品等工业，利润率回到阈值以上后取消补贴，
`privatization.py` 就能把它们卖给私人。补贴每月最多 4 个，优先亏损最重、等级最大的厂。
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
    spec = profile(snap).get("subsidies") or {}
    if not spec:
        return []
    keys = set(spec.get("buildings") or DEFAULT_KEYS)
    low = float(spec.get("max_profitability", 5.0))
    high = float(spec.get("remove_above", 10.0))
    maxn = int(spec.get("max_per_month", 4))
    add: list[tuple] = []
    remove: list[tuple] = []
    for s in snap.states:
        if not s.incorporated:
            continue
        for key, row in s.buildings.items():
            if key not in keys or row.levels <= 0 or row.profitability is None:
                continue
            if row.subsidized:
                if row.profitability > high:
                    remove.append((s, key, row))
            elif row.profitability < low:
                add.append((s, key, row))
    add.sort(key=lambda t: (t[2].profitability or 0.0, -t[2].levels))
    remove.sort(key=lambda t: -(t[2].profitability or 0.0))
    out: list[Decision] = []
    for s, key, row in add[:maxn]:
        out.append(Decision("subsidy", {"state": s.id, "building": key, "on": True},
                            f"补贴亏损工业（{s.name} {key}，利润率 {row.profitability:.0f}%，"
                            f"{row.levels} 级）", score=1e4))
    for s, key, row in remove[:max(0, maxn - len(out))]:
        out.append(Decision("subsidy", {"state": s.id, "building": key, "on": False},
                            f"取消补贴（{s.name} {key} 已盈利 {row.profitability:.0f}%）", score=1e3))
    return out
