"""策略层单测：构造的局面，不需要游戏。"""

from agent import gamedata
from agent.game import Date
from agent.observe import BuildingRow, IGRow, LawOption, LawRow, Snapshot, StateRow
from agent.strategy import budget, construction, consumption, decrees, diplomacy, events, expansion, institutions, politics, privatization, production, research, subsidies, trade
from agent.strategy import config as strategy_config


def _snap(tax_level: str = "Medium", **country) -> Snapshot:
    base = {"money": 1_000_000.0, "gold_limit": 5_000_000.0, "income": 100_000.0, "expenses": 90_000.0,
            "balance": 10_000.0, "construction": 20.0, "construction_used": 20.0, "queue_government": 0.0,
            "tax_waste": 0.0, "legitimacy": 70.0}
    base.update(country)
    return Snapshot(date=Date(1836, 1, 1), name="测试", country=base, tax_level=tax_level, researching=None,
                    laws={}, prices={}, states=[])


def _row(key: str, levels: int = 0, can_queue: bool = True, employed: float = 0.0, wage: float = 120.0,
         employment: float | None = 1.0) -> BuildingRow:
    return BuildingRow(key=key, path=[], levels=levels, queued=0, employment=employment, profitability=None,
                       cash=None, can_queue=can_queue, wage_rate=wage if levels else None, employed=employed)


def test_budget_raises_tax_when_reserve_runs_out():
    d = budget.decide(_snap(balance=-50_000.0, money=500_000.0))
    assert d and d.args["level"] == "High"


def test_budget_keeps_tax_when_reserve_is_deep():
    assert budget.decide(_snap(balance=-1_000.0, money=5_000_000.0)) is None


def test_budget_lowers_tax_when_reserve_full_and_surplus_large():
    d = budget.decide(_snap(balance=40_000.0, money=4_500_000.0))
    assert d and d.args["level"] == "Low"


def test_budget_legitimacy_guards():
    # 高税 + 低合法性：立即回 Medium，不继续收
    d = budget.decide(_snap(tax_level="High", legitimacy=45.0, balance=-1_000.0, money=5_000_000.0))
    assert d and d.args["level"] == "Medium"
    # 合法性不足 62：国库快见底也不升 High
    assert budget.decide(_snap(legitimacy=50.0, balance=-50_000.0, money=500_000.0)) is None
    # 合法性 45–49 且国库充足：降 Low 争取跨过 50
    d = budget.decide(_snap(legitimacy=46.0, balance=-1_000.0, money=9_000_000.0))
    assert d and d.args["level"] == "Low"


def test_research_resolves_prerequisites_first():
    gd = gamedata.get()
    cands = research.candidates(gd, set(), None)
    order = [d.args["tech"] for d in cands]
    # 车床需要轧棉机，轧棉机需要制造厂：前置排在前面
    assert order.index("manufacturies") < order.index("cotton_gin") < order.index("lathe")
    assert research.candidates(gd, set(), "lathe") == []


def test_research_blacklist_skips_trap_techs():
    gd = gamedata.get()
    blocked = {"crystal_glass", "canneries"}
    # 用一条不依赖这两项科技的优先路线，验证补位时跳过黑名单
    order = [d.args["tech"] for d in research.candidates(gd, set(), None, ["lathe"], blocked)]
    assert order and not (blocked & set(order))
    # 但作为优先科技的前置时仍要研究（否则路线会断）
    assert "crystal_glass" in [d.args["tech"] for d in research.candidates(gd, set(), None, ["chemical_bleaching"])]
    assert strategy_config.tech_blacklist(_snap(tag="CHI")) >= {"analytical_philosophy"}


def _opt(key: str, group: str = "lawgroup_land_reform", valid: bool = True, success: float = 0.5,
         stall: float = 0.1, why: str = "", **stance: int) -> LawOption:
    return LawOption(group, key, key, [], valid, why, success, 0.0, stall, 1 - success - stall, dict(stance))


def _qing() -> Snapshot:
    snap = _snap(legitimacy=100.0)
    snap.laws = {"lawgroup_land_reform": LawRow("lawgroup_land_reform", "law_serfdom", "农奴制", []),
                 "lawgroup_army_model": LawRow("lawgroup_army_model", "law_peasant_levies", "征召农兵", [])}
    snap.igs = [IGRow(0, "士大夫", 0.50, True, False), IGRow(1, "军队", 0.15, False, False),
                IGRow(2, "文人", 0.07, False, False), IGRow(3, "实业家", 0.30, False, True)]
    return snap


def test_pass_chance():
    assert politics.pass_chance(_opt("a", success=0.0)) == 0.0
    assert politics.pass_chance(_opt("a", stall=0.0)) == 1.0
    # 推进 : 受阻 = 2 : 1 → 约 0.79；1 : 3 → 很低
    assert abs(politics.pass_chance(_opt("a", success=0.48, stall=0.24)) - 0.790) < 0.01
    assert politics.pass_chance(_opt("a", success=0.09, stall=0.27)) < 0.15


def test_politics_only_enacts_likely_laws():
    snap = _qing()
    opts = [_opt("law_tenant_farmers", success=0.09, stall=0.24),
            _opt("law_professional_army", "lawgroup_army_model", success=0.48, stall=0.24),
            _opt("law_serfdom")]                                     # 已是现行法律
    assert [d.args["law"] for d in politics.candidates(snap, opts, None)] == ["law_professional_army"]
    assert politics.candidates(snap, opts, "某法律") == []


def test_reform_removes_extra_ig_under_autocracy():
    snap = _qing()
    snap.country["legitimacy"] = 46.0
    snap.laws["lawgroup_distribution_of_power"] = LawRow(
        "lawgroup_distribution_of_power", "law_autocracy", "独裁制", [])
    snap.igs = [IGRow(0, "士大夫", 0.50, True, False), IGRow(1, "乡村民众", 0.30, True, False),
                IGRow(2, "小市民", 0.08, True, False)]
    d = politics.reform(snap, [], None)
    assert d and d.kind == "reform_government"
    assert d.args["members"] == [0, 1]          # 只移除小市民，不动统治者/乡村民众


def test_reform_adds_biggest_backer_of_blocked_law():
    snap = _qing()
    blocked = _opt("law_tenant_farmers", valid=False, why="立法成功概率高于0%", 士大夫=-1, 军队=1, 文人=1, 实业家=1)
    d = politics.reform(snap, [blocked], None)
    assert d and d.args == {"members": [0, 1], "add": "军队"}           # 边缘化的实业家不算
    # 缺科技的不是政府能解决的
    tech = _opt("law_tenant_farmers", valid=False, why="大清必须已发明浪漫主义；立法成功概率高于0%", 军队=1)
    assert politics.reform(snap, [tech], None) is None


def test_reform_waits_when_a_law_can_pass_or_legitimacy_low():
    snap = _qing()
    blocked = _opt("law_tenant_farmers", valid=False, why="立法成功概率高于0%", 军队=1)
    ok = _opt("law_professional_army", "lawgroup_army_model", success=0.6, stall=0.1)
    assert politics.reform(snap, [blocked, ok], None) is None
    snap.country["legitimacy"] = 50.0
    assert politics.reform(snap, [blocked], None) is None


def test_construction_needs_labor():
    gd = gamedata.get()
    rich = StateRow(1, 1, "人多", 100.0, 10.0, 50, 2_000_000.0, None)
    rich.buildings = {"building_subsistence_farm": _row("building_subsistence_farm", 100, False, employed=500_000.0),
                      "building_logging_camp": _row("building_logging_camp")}
    empty = StateRow(2, 2, "没人", 100.0, 10.0, 50, 1_000.0, None)
    empty.buildings = {"building_logging_camp": _row("building_logging_camp")}
    snap = _snap()
    snap.states = [rich, empty]
    cands = construction.candidates(gd, snap, set(gd.techs), {"building_logging_camp": 200.0})
    states = {d.args["state"] for d in cands if d.args["building"] == "building_logging_camp"}
    assert states == {1}


def test_construction_stops_when_broke():
    snap = _snap(balance=-100_000.0, money=100_000.0)
    assert construction.slots(snap) == 0
    assert construction.slots(_snap(queue_government=10.0)) == 0


def _event(key: str, *options: dict) -> dict:
    return {"key": key, "title": key, "options": list(options)}


def test_event_policy_avoids_opium_war():
    ev = _event("opium_wars.1",
                {"option": 0, "text": "我们得做点什么！", "desc": "开始鸦片危机", "enabled": True, "default": True},
                {"option": 1, "text": "我们不能得罪大不列颠。", "desc": "增加激进派", "enabled": True, "default": False})
    assert events.pick(ev, "CHI") == 1


def test_event_hardcoded_traps():
    boxer = _event("boxer_rebellion_events.4",
                   {"option": 0, "text": "枷锁被打碎", "desc": "减少 脆弱统一", "enabled": True, "default": True},
                   {"option": 1, "text": "以大局为重，以和解为贵", "desc": "增加 激进", "enabled": True,
                    "default": False})
    assert events.pick(boxer, "CHI") == 1
    heavenly = _event("heavenly.5",
                      {"option": 0, "text": "屠杀剩余异教徒", "desc": "关系 -25", "enabled": True,
                       "default": True},
                      {"option": 1, "text": "展示仁慈，赦免前叛军", "desc": "增加 忠诚", "enabled": True,
                       "default": False})
    assert events.pick(heavenly, "CHI") == 1
    famine = _event("famine_political.1",
                    {"option": 0, "text": "坚持传统不应该以生命为代价", "desc": "贸易容量 +20%",
                     "enabled": True, "default": False},
                    {"option": 1, "text": "农民哪个年代不挨饿", "desc": "增加 激进", "enabled": True,
                     "default": True})
    assert events.pick(famine, "CHI") == 0


def test_event_policy_prefers_good_effects():
    ev = _event("generic.1",
                {"option": 0, "text": "改革", "desc": "增加 10% 创新，减少 5 生活水平",
                 "enabled": True, "default": False},
                {"option": 1, "text": "维持", "desc": "增加激进派，减少征税能力", "enabled": True, "default": True})
    assert events.score(ev, ev["options"][0]) > events.score(ev, ev["options"][1])
    assert events.pick(ev, "CHI") == 0


def test_institutions_follow_profile_and_wait_for_bureaucracy():
    snap = _snap(tag="CHI", tax_waste=0.0)
    snap.institutions = ["教育"]                 # 学校法未过时列表里没有教育，不会硬发动作
    assert [d.args["institution"] for d in institutions.candidates(snap)] == ["教育"]
    snap.country["tax_waste"] = 0.3
    assert institutions.candidates(snap) == []
    snap.country["tax_waste"] = 0.0
    snap.institutions = []
    assert institutions.candidates(snap) == []
    snap.institutions = ["教育", "卫生系统"]
    assert {d.args["institution"] for d in institutions.candidates(snap)} == {"教育", "卫生系统"}
    snap.country["balance"] = -1_000.0           # 结余为负：先别加机构
    assert institutions.candidates(snap) == []


def test_decrees_pick_big_and_overused_states():
    snap = _snap(tag="CHI")
    big = StateRow(0, 1, "大州", 100.0, 120.0, 50, 20_000_000.0, None)
    small = StateRow(1, 2, "小州", 100.0, 10.0, 50, 5_000_000.0, None)
    snap.states = [big, small]
    got = {(d.args["state"], d.args["decree"]) for d in decrees.candidates(snap)}
    assert got == {(1, "促进社会流动"), (1, "道路养护")}
    hungry = StateRow(2, 3, "饥荒州", 10.0, 10.0, 50, 1_000_000.0, None)
    hungry.famine = True
    snap.states.append(hungry)
    assert (3, "紧急救济") in {(d.args["state"], d.args["decree"]) for d in decrees.candidates(snap)}


def test_shortage_helpers():
    snap = _snap()
    snap.prices = {"meat": {"buy": 200.0, "sell": 100.0}, "grain": {"buy": 100.0, "sell": 100.0}}
    assert construction._buy_sell_ratio(snap, "meat") == 2.0
    assert construction._food_short(snap, {"food_security": {"goods": ["meat"], "trigger_ratio": 1.5}})
    assert not construction._food_short(snap, {"food_security": {"goods": ["grain"], "trigger_ratio": 1.5}})


def test_profile_politics_override():
    snap = _snap(tag="CHI", legitimacy=100.0)
    p = politics._pcfg(snap)
    assert p["min_pass"] == 0.35 and p["max_government"] == 3


def test_reform_removes_smallest_when_government_illegitimate():
    snap = _qing()
    snap.country["legitimacy"] = 19.0
    snap.igs = [IGRow(0, "士大夫", 0.50, True, False), IGRow(1, "军队", 0.10, True, False),
                IGRow(2, "文人", 0.05, False, False)]
    d = politics.reform(snap, [], None)
    assert d and d.args["members"] == [0] and "移除" in d.why


def test_subsidies_add_and_remove():
    snap = _snap(tag="CHI")
    s = StateRow(0, 1, "州", 100.0, 10.0, 50, 10_000_000.0, None)
    row = _row("building_textile_mill", levels=5)
    row.earnings, row.wages_expense = 0.0, 50.0   # 实际周利润 −50
    row.subsidized = False
    s.buildings = {"building_textile_mill": row}
    snap.states = [s]
    got = subsidies.candidates(snap)
    assert got and got[0].args["on"] is True
    row.subsidized = True
    row.earnings, row.wages_expense = 120.0, 0.0  # 实际为正：取消补贴
    got = subsidies.candidates(snap)
    assert got and got[0].args["on"] is False


def test_subsidies_cap_total_share():
    snap = _snap(tag="CHI", income=100_000.0, subsidies=50_000.0)
    s = StateRow(0, 1, "州", 100.0, 10.0, 50, 10_000_000.0, None)
    row = _row("building_textile_mill", levels=10)
    row.subsidized = True
    row.earnings, row.wages_expense = 0.0, 50.0
    row.subsidy_cost = 20_000.0
    s.buildings = {"building_textile_mill": row}
    snap.states = [s]
    got = subsidies.candidates(snap)
    assert got and got[0].args["on"] is False and "超过收入" in got[0].why


def test_consumption_tax_one_at_a_time_and_authority_gate():
    snap = _snap(tag="CHI", authority=350.0, legitimacy=50.0, sol=7.0)
    snap.taxed_goods = set()
    got = consumption.candidates(snap)
    assert got and got[0].args["goods"] == "tea"
    snap.country["authority"] = 150.0                # 连 100 成本 + 100 缓冲都不够
    assert consumption.candidates(snap) == []
    snap.country["authority"] = 900.0
    snap.taxed_goods = {"tea", "liquor", "opium", "tobacco", "sugar", "porcelain"}
    assert consumption.candidates(snap) == []


def test_trade_policy_shortage_and_surplus():
    snap = _snap(tag="CHI")
    snap.prices = {"meat": {"buy": 200.0, "sell": 100.0}, "wood": {"buy": 100.0, "sell": 100.0}}
    snap.trade_policies = {"meat": {"Import": "TariffsLow", "Export": "TariffsLow"},
                           "wood": {"Import": "TariffsLow", "Export": "TariffsLow"}}
    args = {(d.args["goods"], d.args["side"], d.args["policy"]) for d in trade.candidates(snap)}
    assert ("meat", "Import", "TariffsNone") in args
    assert ("meat", "Export", "TariffsHigh") in args
    # 已经是目标政策：不重复发（游戏有 3 个月冷却，乱翻会一直撞墙）
    snap.trade_policies["meat"] = {"Import": "TariffsNone", "Export": "TariffsHigh"}
    assert not [d for d in trade.candidates(snap) if d.args["goods"] == "meat"]
    # 过剩：进口高关税保护本国产业
    snap.prices["wood"] = {"buy": 100.0, "sell": 200.0}
    args = {(d.args["goods"], d.args["side"], d.args["policy"]) for d in trade.candidates(snap)}
    assert ("wood", "Import", "TariffsHigh") in args


def test_production_scans_priority_industries_first():
    gd = gamedata.get()
    snap = _snap(tag="CHI")
    states = []
    for i in range(15):                          # 大量高等级非优先建筑占满轮转前排
        s = StateRow(i, i + 1, f"农场{i}", 100.0, 10.0, 50, 10_000_000.0, None)
        s.buildings = {"building_wheat_farm": _row("building_wheat_farm", levels=100)}
        states.append(s)
    paper = StateRow(99, 99, "纸厂", 100.0, 10.0, 50, 10_000_000.0, None)
    paper.buildings = {"building_paper_mill": _row("building_paper_mill", levels=5)}
    states.append(paper)
    snap.states = states
    got = production.candidates(gd, snap, set(gd.techs))
    assert any(d.args["building"] == "building_paper_mill" for d in got)


def test_financial_district_stays_privately_owned():
    gd = gamedata.get()
    snap = _snap(tag="CHI")
    s = StateRow(0, 1, "州", 100.0, 10.0, 50, 10_000_000.0, None)
    s.buildings = {"building_financial_district": _row("building_financial_district", levels=5)}
    snap.states = [s]
    got = production.financial_candidates(gd, snap, set(gd.techs))
    assert got and got[0].args["pm"] == "pm_financial_district_privately_owned"


def test_incorporate_unincorporated_states():
    snap = _snap(tag="CHI", tax_waste=0.05)
    s = StateRow(0, 1, "边疆", 10.0, 10.0, 50, 2_000_000.0, None)
    s.incorporated = False
    s.can_incorporate = True
    snap.states = [s]
    got = expansion.candidates(snap)
    assert got and got[0].kind == "state_action" and got[0].args["cmd"] == "IncorporateState"
    s.incorporating = True
    assert expansion.candidates(snap) == []


def test_privatization_candidates():
    snap = _snap(tag="CHI")
    s = StateRow(0, 1, "州", 100.0, 10.0, 50, 10_000_000.0, None)
    row = _row("building_textile_mill", levels=3)
    row.can_toggle_privatization = True
    row.can_privatize = False
    row.earnings, row.wages_expense = 120.0, 100.0
    s.buildings = {"building_textile_mill": row}
    snap.states = [s]
    got = privatization.candidates(snap)
    assert got and got[0].kind == "privatize" and got[0].args["building"] == "building_textile_mill"
    row.can_privatize = True                      # 开关已开：再提案会把它关掉
    assert privatization.candidates(snap) == []
    row.can_privatize = False
    row.earnings = 0.0                            # 负利润：没有买家
    assert privatization.candidates(snap) == []


def test_diplomacy_rejects_demands_and_sway():
    assert not diplomacy.accept_proposal({"kind": "demand", "name": "割让香港", "actor": "英国"})
    assert not diplomacy.accept_proposal({"kind": "sway", "name": "加入战争", "actor": "法国"})


def test_diplomacy_accepts_defensive_pact_rejects_investment_rights():
    assert diplomacy.accept_proposal({"kind": "treaty", "name": "防御同盟", "actor": "俄国"})
    assert not diplomacy.accept_proposal({"kind": "treaty", "name": "投资权", "actor": "英国"})


def test_construction_sector_sized_to_income():
    gd = gamedata.get()
    st = StateRow(1, 1, "首府", 100.0, 10.0, 50, 2_000_000.0, None)
    st.buildings = {"building_construction_sector": _row("building_construction_sector", 2)}
    poor = _snap(income=5_000.0, expenses=4_000.0, balance=1_000.0, money=1_000_000.0)
    poor.states = [st]
    assert not [d for d in construction.candidates(gd, poor, set(gd.techs), {})
                if d.args["building"] == "building_construction_sector"]
    rich = _snap(income=500_000.0, expenses=300_000.0, balance=200_000.0, money=5_000_000.0)
    rich.states = [st]
    assert [d for d in construction.candidates(gd, rich, set(gd.techs), {})
            if d.args["building"] == "building_construction_sector"]
