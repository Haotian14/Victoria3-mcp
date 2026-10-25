"""预算、现金支出护栏与税级。

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


def emergency(snap: Snapshot) -> bool:
    """赤字或不足八周总支出即削支；信用额度不算现金储备。"""
    c = snap.country
    money, expenses, balance = (c.get(k) for k in ("money", "expenses", "balance"))
    if any(v is None for v in (money, expenses, balance)):
        return True
    return bool(c.get("in_default") or c.get("bankrupt") or c.get("loan_penalty") or money <= 0 or balance < 0
                or money < expenses * float(cfg()["budget"].get("emergency_reserve_weeks", 8)))


def can_spend(snap: Snapshot, upfront: float = 0.0, weekly: float = 0.0) -> bool:
    """先留八周支出和四周新增成本；不把剩余信用当可花的钱。"""
    if emergency(snap):
        return False
    c = snap.country
    cash = float(c.get("money") or 0) - max(0, upfront)
    pending = float(c.get("reserved_weekly") or 0)
    projected = float(c.get("balance") or 0) - max(0, weekly) - pending
    reserve = (float(c.get("expenses") or 0) + max(0, weekly) + pending) * float(
        cfg()["budget"].get("emergency_reserve_weeks", 8))
    return projected >= 0 and cash > reserve + max(0, weekly) * 4


def construction_allowance(snap: Snapshot) -> tuple[int, float]:
    """按持续盈余负担政府项目，不把国库存量或剩余信用当收入。

    商品费用包括私营建造；必须用总已用点数作分母，不能除以政府点数。
    无活动建造时采用保守报价，不能把未知成本当0。25点来自本版本项目上限实测；
    运行中观察到更高项目速度时由runner提高project_construction_points。
    """
    c = snap.country
    if emergency(snap):
        return 0, 0.0
    spec = cfg()["budget"].get("construction_recovery") or {}
    used, goods = float(c.get("construction_used") or 0), float(c.get("construction_goods") or 0)
    unit = goods / used if used > 0 and goods > 0 else float(spec.get("unknown_cost_per_point", 3000))
    gov_used, gov_goods = (float(c.get(k) or 0) for k in (
        "government_construction_used", "government_construction_goods"))
    if gov_used > 0 and gov_goods > 0:
        unit = max(unit, gov_goods / gov_used)
    # 免费基础点数和暂停后一帧的费用/用量重算可能压低观测单价，保留保守底价。
    unit = max(unit, float(spec.get("min_cost_per_point", 1000)))
    points = max(float(spec.get("project_points", 25)), float(c.get("project_construction_points") or 0))
    points = min(points, max(0, float(c.get("construction") or 0)))
    cost = unit * points * float(spec.get("cost_buffer", 1.05))
    if cost <= 0:
        return 0, 0.0
    # 已结算的政府费用加回，得到可在项目间重新分配的持续预算。
    headroom = max(0, float(c.get("balance") or 0) + gov_goods - float(c.get("reserved_weekly") or 0))
    available = max(0, headroom - max(float(spec.get("minimum_surplus", 1000)),
                                    headroom * (1 - float(spec.get("surplus_share", 0.95)))))
    limit = min(int(spec.get("max_projects", 8)), int(available // cost))
    return max(0, limit), cost


def action_block(snap: Snapshot, d: Decision, fragile_unity: int | None = None) -> str:
    """执行层兜底，避免候选、保底槽或旧计划绕过财政护栏。"""
    text = f"{d.kind} {d.args}".lower()
    if any(k in text for k in ("declarebankruptcy", "bankruptcy", "take_loan", "borrow", "default")):
        return "禁止主动借款/破产/违约"  # 当前策略全部以现金支付，≤4 时也没有例外
    if fragile_unity is not None and fragile_unity <= 4:
        if any(k in text for k in ("revolution", "革命", "start_civil_war")):
            return "脆弱的统一≤4，禁止革命动作"
    spending = d.kind in ("build", "set_institution")
    if d.kind == "build" and snap.country.get("construction_paused"):
        return "政府建造尚未恢复，停止新增排队"
    spending |= d.kind == "subsidy" and d.args.get("on", False)
    spending |= d.kind == "trade_policy" and str(d.args.get("policy", "")).startswith("Subventions")
    spending |= d.kind == "set_pm" and d.args.get("building") in (
        "building_construction_sector", "building_university", "building_government_administration",
        "building_barracks", "building_barrack", "building_naval_base")
    weekly = float(d.args.get('operating_weekly') or 0)
    if weekly and d.kind == 'build':
        weekly += construction_allowance(snap)[1]
    if spending and not can_spend(snap, weekly=weekly):
        return "财政紧急模式：停止新增支出"
    if d.kind == "set_tax" and (snap.country.get("legitimacy") or 0) < 60:
        target = d.args.get("level")
        current = snap.tax_level
        if target in TAX_LEVELS and current in TAX_LEVELS and TAX_LEVELS.index(target) > TAX_LEVELS.index(current):
            return "合法性<60，禁止加税"
    if d.kind == "set_tax":
        ceiling = profile(snap).get("tax_ceiling")
        target = d.args.get("level")
        if ceiling in TAX_LEVELS and target in TAX_LEVELS and TAX_LEVELS.index(target) > TAX_LEVELS.index(ceiling):
            return f"财政诊断税级上限 {ceiling}，先削支"
    return ""


def decide(snap: Snapshot) -> Decision | None:
    c = cfg()["budget"]
    level = snap.tax_level
    if level not in TAX_LEVELS:
        return None
    i = TAX_LEVELS.index(level)
    ceiling = profile(snap).get("tax_ceiling", c["max_tax"])
    hi, lo = TAX_LEVELS.index(ceiling), TAX_LEVELS.index(c["min_tax"])
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
    # 攻略：晚期国库充足时降税，让钱留在人民手里拉动内需/SoL；前期仍守住 Medium。
    late_year = int(c.get("late_low_tax_year", 0) or 0)
    late_ok = bool(late_year and snap.date.year >= late_year and limit
                   and money > limit * float(c.get("late_low_tax_reserve_ratio", 1.5))
                   and balance > income * float(c.get("late_low_tax_surplus_over", 0.1)))
    eff_lo = TAX_LEVELS.index("Low") if late_ok else max(lo, fi)
    if i > hi:
        return Decision("set_tax", {"level": ceiling}, f"财政诊断税级上限 {ceiling}，停止用高税维持支出")

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
    if i < fi and not late_ok and leg < 55 and rich and small_deficit:
        return None
    if balance < 0 and money < -balance * c["deficit_weeks"] and i < hi and not (rich and small_deficit):
        if leg < 60:
            return None
        target = TAX_LEVELS[i + 1]
        if target == "High" and leg < c.get("tax_up_legitimacy", 62):
            return None                      # 合法性不够：先砍补贴/开消费税，不升税
        if target == "VeryHigh" and leg < c.get("very_high_legitimacy", 95):
            return None
        return Decision("set_tax", {"level": target},
                        f"每周赤字 {-balance:,.0f}，国库 {money:,.0f} 只够 {money / -balance:.0f} 周")
    if i < fi and not late_ok:
        if leg < 60:
            return None
        return Decision("set_tax", {"level": TAX_LEVELS[i + 1]},
                        f"攻略建议税级不低于 {floor}（当前 {level}）")
    if (late_ok and i > TAX_LEVELS.index("Low")
            and balance > income * float(c.get("late_low_tax_surplus_over", 0.1))):
        return Decision("set_tax", {"level": TAX_LEVELS[i - 1]},
                        f"晚期国库 {money:,.0f} 充足，降税拉动内需与 SoL（攻略）")
    if (balance > income * c["lower_when_surplus_over"] and limit and money > limit * c["lower_when_reserve_over"]
            and i > eff_lo and not (50 <= leg < 55)):
        return Decision("set_tax", {"level": TAX_LEVELS[i - 1]},
                        f"结余 {balance:,.0f}/周、国库 {money:,.0f} 已近储备上限 {limit:,.0f}，减税")
    return None


def government_wage_level(snap: Snapshot, at_war: bool) -> str:
    """攻略：前期政府工资压 Low 换建造资金；重商主义（承认 JE 激活）后回 Medium。
    军队工资不走这里：财政护栏统一为和平 Low、战时 Medium。"""
    w = profile(snap).get("wages") or {}
    until = int(w.get("government_low_until_year", 0) or 0)
    trade = snap.laws.get("lawgroup_trade_policy")
    merc = bool(trade and trade.key == "law_mercantilism")
    before_ok = (not w.get("government_low_before_mercantilism", True)) or not merc
    if not at_war and until and snap.date.year < until and before_ok:
        return "Low"
    return "Medium"
