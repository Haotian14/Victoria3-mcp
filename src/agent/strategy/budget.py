"""预算：只调税级。

依据（vic3.paradoxwikis.com/Budget，1.13）：
- 结余进金储备，储备软上限是年 GDP 的 20%（GetGoldReserveLimit），超出后收益递减 —— 多出来的钱应当花掉（多建）或还给民众（减税）；
- 储备耗尽后赤字变贷款，基础利率 20%，未被承认的大国 ×2；本金到信用上限一半即「经济不健康」；
- 税级：高税 −10% 合法性、激进 +50%；极高 −20% / +100%。低税 +5% 合法性、激进 −10%。

规则：入不敷出且储备撑不过 deficit_weeks 周 → 加一级（最多到 max_tax）；
结余超过收入的 lower_when_surplus_over 且储备超过上限的 lower_when_reserve_over → 减一级（最低 min_tax）。
"""

from __future__ import annotations

from agent.observe import TAX_LEVELS, Snapshot
from agent.strategy.config import Decision, cfg


def decide(snap: Snapshot) -> Decision | None:
    c = cfg()["budget"]
    level = snap.tax_level
    if level not in TAX_LEVELS:
        return None
    i = TAX_LEVELS.index(level)
    hi, lo = TAX_LEVELS.index(c["max_tax"]), TAX_LEVELS.index(c["min_tax"])
    money = snap.country.get("money") or 0.0
    balance = snap.country.get("balance") or 0.0
    income = snap.country.get("income") or 0.0
    limit = snap.country.get("gold_limit") or 0.0

    if balance < 0 and money < -balance * c["deficit_weeks"] and i < hi:
        return Decision("set_tax", {"level": TAX_LEVELS[i + 1]},
                        f"每周赤字 {-balance:,.0f}，国库 {money:,.0f} 只够 {money / -balance:.0f} 周")
    if (balance > income * c["lower_when_surplus_over"] and limit and money > limit * c["lower_when_reserve_over"]
            and i > lo):
        return Decision("set_tax", {"level": TAX_LEVELS[i - 1]},
                        f"结余 {balance:,.0f}/周、国库 {money:,.0f} 已近储备上限 {limit:,.0f}，减税")
    return None
