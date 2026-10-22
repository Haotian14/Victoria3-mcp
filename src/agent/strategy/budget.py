"""预算：只调税级。

依据（vic3.paradoxwikis.com/Budget，1.13）：
- 结余进金储备，储备软上限是年 GDP 的 20%（GetGoldReserveLimit），超出后收益递减 —— 多出来的钱应当花掉（多建）或还给民众（减税）；
- 储备耗尽后赤字变贷款，基础利率 20%，未被承认的大国 +50%（约 30%，不是 ×2）；
  本金到信用上限一半即「经济不健康」；
- 税级：高税 −10 合法性、激进 +50%；极高 −20 / +100。低税 +5 合法性、激进 −10。

规则：入不敷出且储备撑不过 deficit_weeks 周 → 加一级（最多到 max_tax）；
结余超过收入的 lower_when_surplus_over 且储备超过上限的 lower_when_reserve_over → 减一级（最低 min_tax）。
财政调研（1856，1.13.11）加的护栏：
- High/VeryHigh 且合法性 < legitimacy_guard → 立即回 Medium（掉进 Unacceptable 会 −25% 立法速度）；
- 升 High 要合法性 ≥ tax_up_legitimacy，VeryHigh 要 ≥ very_high_legitimacy（几乎不用）；
- 国库 > reserve_guard 倍上限、赤字不超过收入 deficit_tolerance 时，不靠税级解决；
- 合法性 45–49 且国库充足时降一级，争取跨过 50（Unacceptable → Contested）；
- 合法性 50–54 时不要为了花钱而降税（降到 Low 也跨不过 75，白送收入）。
"""

from __future__ import annotations

from agent.observe import TAX_LEVELS, Snapshot
from agent.strategy.config import Decision, cfg, profile


def decide(snap: Snapshot) -> Decision | None:
    c = cfg()["budget"]
    level = snap.tax_level
    if level not in TAX_LEVELS:
        return None
    i = TAX_LEVELS.index(level)
    hi, lo = TAX_LEVELS.index(c["max_tax"]), TAX_LEVELS.index(c["min_tax"])
    floor = profile(snap).get("tax_floor")       # 国家档案：税级不低于此级（大清 Medium）
    fi = TAX_LEVELS.index(floor) if floor in TAX_LEVELS else lo
    money = snap.country.get("money") or 0.0
    balance = snap.country.get("balance") or 0.0
    income = snap.country.get("income") or 0.0
    limit = snap.country.get("gold_limit") or 0.0
    leg = snap.country.get("legitimacy") or 0.0
    medium = TAX_LEVELS.index("Medium")
    rich = bool(limit) and money > limit * c.get("reserve_guard", 1.5)
    small_deficit = balance >= 0 or -balance <= income * c.get("deficit_tolerance", 0.03)

    # 合法性护栏：高税掉进 Unacceptable 的代价大于多收的税
    if i > medium and leg < c.get("legitimacy_guard", 60):
        return Decision("set_tax", {"level": "Medium"},
                        f"合法性 {leg:.0f} 低于 {c.get('legitimacy_guard', 60)}，"
                        f"从 {level} 回 Medium（避免 Unacceptable 的立法惩罚）")
    # 合法性 45–49：降一级买到 +5，争取跨过 50
    if (level == "Medium" and 45 <= leg < 50 and rich and small_deficit and i > max(lo, fi)):
        return Decision("set_tax", {"level": "Low"},
                        f"合法性 {leg:.0f}，降税 +5 争取跨过 50（国库充足）")
    # 为跨阈值而降的 Low 先不要急着加回 Medium
    if i < fi and leg < 55 and rich and small_deficit:
        return None
    if balance < 0 and money < -balance * c["deficit_weeks"] and i < hi and not (rich and small_deficit):
        target = TAX_LEVELS[i + 1]
        if target == "High" and leg < c.get("tax_up_legitimacy", 62):
            return None                      # 合法性不够：先砍补贴/开消费税，不升税
        if target == "VeryHigh" and leg < c.get("very_high_legitimacy", 95):
            return None
        return Decision("set_tax", {"level": target},
                        f"每周赤字 {-balance:,.0f}，国库 {money:,.0f} 只够 {money / -balance:.0f} 周")
    if i < fi:
        return Decision("set_tax", {"level": TAX_LEVELS[i + 1]},
                        f"攻略建议税级不低于 {floor}（当前 {level}）")
    if (balance > income * c["lower_when_surplus_over"] and limit and money > limit * c["lower_when_reserve_over"]
            and i > max(lo, fi) and not (50 <= leg < 55)):
        return Decision("set_tax", {"level": TAX_LEVELS[i - 1]},
                        f"结余 {balance:,.0f}/周、国库 {money:,.0f} 已近储备上限 {limit:,.0f}，减税")
    return None
