"""补贴关键工业：先止损保就业，等盈利后取消补贴，让私有化能接手（养大实业家）。

大清 1.13 攻略链：学校法只有实业家支持 → 实业家需要持有盈利的工厂 → 亏损厂没人买；
先补贴纺织 / 家具 / 玻璃 / 工具 / 造纸 / 食品等工业，利润率回到阈值以上后取消补贴，
`privatization.py` 就能把它们卖给私人。

但 1856 实测补贴累计到 29 个建筑、约 49k/周（收入的 10.9%），私有化仍为 0，
所以加两道闸：总额不超过收入的 max_total_share（默认 3%），超出时优先取消补贴金额最大的
非战略建筑（工具/造纸/军工保护）；新建补贴也必须给总额留出余量。
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
    # 实际现金流：GetProfitability 是“相对世界平均的生产率”，不是盈亏
    max_profit = float(spec.get("max_profit", 0.0))
    maxn = int(spec.get("max_per_month", 2))
    max_remove = int(spec.get("max_remove_per_month", 3))
    min_level = int(spec.get("min_level", 3))
    protect = set(spec.get("protect_buildings") or ())
    income = snap.country.get("income") or 0.0
    room = income * float(spec.get("max_total_share", 0.03))
    total = snap.country.get("subsidies")
    if total is None:
        total = sum(r.subsidy_cost for s in snap.states for r in s.buildings.values() if r.subsidized)
    add: list[tuple] = []
    remove: list[tuple[str, tuple]] = []
    for s in snap.states:
        if not s.incorporated:
            continue
        for key, row in s.buildings.items():
            if key not in keys or row.levels <= 0:
                continue
            if row.subsidized:
                why = ""
                if row.profit > 0:
                    why = f"实际周利润 +{row.profit:,.0f}"
                elif row.levels < min_level:
                    why = f"只有 {row.levels} 级"
                elif room and total > room and key not in protect:
                    why = f"补贴总额 {total:,.0f}/周超过收入的 {spec.get('max_total_share', 0.03):.0%}"
                if why:
                    remove.append((why, (s, key, row)))
            elif row.profit < max_profit and row.levels >= min_level:
                add.append((s, key, row))
    # 先砍省钱最多的（GetSubsidies 的周支出），再砍小额
    remove.sort(key=lambda t: -(t[1][2].subsidy_cost or 0.0))
    add.sort(key=lambda t: (t[2].profit, -t[2].levels))
    out: list[Decision] = []
    projected = total
    for why, (s, key, row) in remove[:max_remove]:
        out.append(Decision("subsidy", {"state": s.id, "building": key, "on": False},
                            f"取消补贴（{s.name} {key}：{why}，省 {row.subsidy_cost:,.0f}/周）", score=1e3))
        projected -= row.subsidy_cost or 0.0
    for s, key, row in add[:maxn]:
        if room and projected >= room:
            break                             # 先给总额腾空间，再补贴新的厂
        out.append(Decision("subsidy", {"state": s.id, "building": key, "on": True},
                            f"补贴亏损工业（{s.name} {key}，实际周利润 {row.profit:,.0f}，"
                            f"{row.levels} 级）", score=1e4))
    return out
