"""策略层单测：构造的局面，不需要游戏。"""

from agent import gamedata, runner
from agent.game import Date
from agent.observe import BuildingRow, CompanyInfo, IGRow, LawOption, LawRow, Snapshot, StateRow
from agent.strategy import budget, companies, construction, consumption, decrees, diplomacy, events, expansion, institutions, politics, privatization, production, research, subsidies, trade
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


def test_budget_keeps_tax_at_medium_when_reserve_full_and_surplus_large():
    assert budget.decide(_snap(balance=40_000.0, money=4_500_000.0)) is None


def test_budget_late_low_tax_when_rich():
    snap = _snap(tag="CHI", money=9_000_000.0, gold_limit=5_000_000.0, balance=40_000.0)
    snap.date = Date(1862, 1, 1)
    d = budget.decide(snap)
    assert d and d.args["level"] == "Low"
    early = _snap(tag="CHI", money=9_000_000.0, gold_limit=5_000_000.0, balance=40_000.0)
    assert budget.decide(early) is None


def test_budget_legitimacy_guards():
    # 高税 + 低合法性：立即回 Medium，不继续收
    d = budget.decide(_snap(tax_level="High", legitimacy=45.0, balance=-1_000.0, money=5_000_000.0))
    assert d and d.args["level"] == "Medium"
    # 合法性不足 62：国库快见底也不升 High
    assert budget.decide(_snap(legitimacy=50.0, balance=-50_000.0, money=500_000.0)) is None
    # 合法性 45–49 且国库充足：高税降一级到 Medium（v6 下限固定 Medium）
    d = budget.decide(_snap(tax_level="High", legitimacy=46.0, balance=-1_000.0, money=9_000_000.0))
    assert d and d.args["level"] == "Medium"


def test_government_wage_low_before_mercantilism():
    snap = _snap(tag="CHI")
    assert budget.government_wage_level(snap, at_war=False) == "Low"
    assert budget.government_wage_level(snap, at_war=True) == "Medium"
    snap.laws["lawgroup_trade_policy"] = LawRow("lawgroup_trade_policy", "law_mercantilism", "重商主义", [])
    assert budget.government_wage_level(snap, at_war=False) == "Medium"
    snap.laws = {}
    snap.date = Date(1846, 1, 1)
    assert budget.government_wage_level(snap, at_war=False) == "Medium"


def test_research_resolves_prerequisites_first():
    gd = gamedata.get()
    cands = research.candidates(gd, set(), None)
    order = [d.args["tech"] for d in cands]
    # 车床需要轧棉机，轧棉机需要制造厂：前置排在前面
    assert order.index("manufacturies") < order.index("cotton_gin") < order.index("lathe")
    assert research.candidates(gd, set(), "lathe") == []


def test_chinese_tech_priority_puts_research_and_steel_first():
    order = strategy_config.tech_priority(_snap(tag="CHI"))
    assert order[0] == "stock_exchange"
    assert order.index("stock_exchange") < order.index("colonization")
    assert order.index("colonization") < order.index("empiricism")
    assert order.index("chemical_bleaching") < order.index("railways")
    assert order.index("railways") < order.index("watertube_boiler")
    assert order.index("watertube_boiler") < order.index("bessemer_process")
    assert order.index("bessemer_process") < order.index("mechanical_tools")
    assert order.index("mechanical_tools") < order.index("steel_frame_buildings")
    assert order.index("steel_frame_buildings") < order.index("corporate_charters")
    assert order.index("steel_frame_buildings") < order.index("line_infantry")


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


def test_law_fallback_after_deadlock():
    snap = _qing()
    snap.country["tag"] = "CHI"                 # 兜底列表在 CHI 档案里
    snap.laws["lawgroup_economic_system"] = LawRow(
        "lawgroup_economic_system", "law_traditionalism", "传统主义", [])
    snap.laws["lawgroup_distribution_of_power"] = LawRow(
        "lawgroup_distribution_of_power", "law_autocracy", "独裁制", [])
    snap.laws["lawgroup_education_system"] = LawRow(
        "lawgroup_education_system", "law_no_schools", "无学校", [])
    agr = _opt("law_agrarianism", "lawgroup_economic_system", success=0.12, stall=0.2)
    olig = _opt("law_oligarchy", "lawgroup_distribution_of_power", success=0.12, stall=0.2)
    bad = _opt("law_public_schools", "lawgroup_education_system", success=0.09, stall=0.24)
    opts = [agr, olig, bad]
    assert politics.candidates(snap, opts, None) == []          # 正常门槛 35%：都不推
    threshold = politics.fallback_threshold(snap)
    assert threshold == 6                                       # 法律失败后最多空转 6 个月
    assert not politics.fallback_ready(snap, threshold - 1)
    assert politics.fallback_ready(snap, threshold)
    got = [d.args["law"] for d in politics.candidates(snap, opts, None, fallback=True)]
    assert got[0] == "law_agrarianism"                          # 兜底优先农本主义
    assert "law_oligarchy" in got and "law_public_schools" not in got


def test_law_vanished_detects_failed_enactment():
    snap = _qing()
    snap.laws["lawgroup_land_reform"] = LawRow(
        "lawgroup_land_reform", "law_serfdom", "农奴制", [])
    assert runner.law_vanished("law_tenant_farmers", snap)      # 上月推的法没生效
    assert not runner.law_vanished("law_serfdom", snap)         # 现行法不算失败
    assert not runner.law_vanished(None, snap)


def test_situation_alerts_summary():
    snap = _snap(tag="CHI", sol=6.5, legitimacy=40.0, balance=-10_000.0, money=100_000.0)
    snap.prices = {"meat": {"buy": 300.0, "sell": 100.0, "price": 45.0, "base": 30.0}}
    alerts = runner._situation_alerts(snap, runner.Memory())
    assert any("缺货 meat" in a for a in alerts)
    assert any("合法性 40" in a for a in alerts)
    assert any("SoL 6.50" in a for a in alerts)


def test_metrics_include_law_and_industrialist_summary():
    snap = _snap(gdp=1_000_000.0, population=100_000.0)
    snap.laws = {"lawgroup_land_reform": LawRow("lawgroup_land_reform", "law_tenant_farmers", "佃农", [])}
    snap.igs = [IGRow(0, "士大夫", 0.50, True, False), IGRow(1, "实业家", 0.06, False, False)]
    m = runner.metrics(snap)
    assert m["gdp_per_capita"] == 10.0
    assert m["laws"] == 1 and m["industrialists_clout"] == 0.06
    assert m["government"] == "士大夫"


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
    snap = _snap(tag="CHI", authority=350.0, legitimacy=50.0, sol=9.0)
    snap.taxed_goods = set()
    got = consumption.candidates(snap)
    assert got and got[0].args["goods"] == "services" and got[0].args["on"] is True
    snap.country["authority"] = 150.0                # 连 100 成本 + 100 缓冲都不够
    assert consumption.candidates(snap) == []
    snap.country["authority"] = 900.0
    snap.taxed_goods = {"services", "tea"}           # 目标 1 项：先退靠后的茶
    got = consumption.candidates(snap)
    assert got and got[0].args == {"goods": "tea", "on": False}


def test_consumption_tax_repeals_to_one_when_sol_low():
    snap = _snap(tag="CHI", authority=900.0, legitimacy=50.0, sol=7.0)
    snap.taxed_goods = {"services", "tea"}
    got = consumption.candidates(snap)
    assert got and got[0].args == {"goods": "tea", "on": False}
    snap.taxed_goods = {"services"}
    assert consumption.candidates(snap) == []        # 只留服务税，不再新开
    snap.taxed_goods = {"services", "tea"}
    snap.country.update(balance=-50_000.0, money=100_000.0)
    assert consumption.candidates(snap) == []        # 国库撑不住：先不退


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
    snap.prices["fabric"] = {"buy": 100.0, "sell": 200.0}
    snap.trade_policies["fabric"] = {"Import": "TariffsLow", "Export": "TariffsLow"}
    args = {(d.args["goods"], d.args["side"], d.args["policy"]) for d in trade.candidates(snap)}
    assert ("fabric", "Import", "TariffsHigh") in args


def test_trade_watches_consumer_goods_and_price_oversupply():
    snap = _snap(tag="CHI")
    snap.prices = {"paper": {"buy": 400.0, "sell": 200.0, "price": 47.0, "base": 30.0},
                   "furniture": {"buy": 100.0, "sell": 100.0, "price": 20.0, "base": 30.0}}
    snap.trade_policies = {"paper": {"Import": "TariffsLow", "Export": "TariffsLow"},
                           "furniture": {"Import": "TariffsLow", "Export": "TariffsLow"}}
    args = {(d.args["goods"], d.args["side"], d.args["policy"]) for d in trade.candidates(snap)}
    assert ("paper", "Import", "TariffsNone") in args          # 高价纸张：进口零关税
    assert ("paper", "Export", "TariffsHigh") in args
    assert ("furniture", "Import", "TariffsHigh") in args      # 价格低于基准：进口高关税
    assert ("furniture", "Export", "TariffsNone") in args      # 出口侧也处理：零关税鼓励外销


def test_trade_paper_je_uses_import_subventions():
    snap = _snap(tag="CHI")
    snap.journal_keys = {"je_set_up_paper_import"}
    snap.prices = {"paper": {"buy": 400.0, "sell": 200.0, "price": 47.0, "base": 30.0}}
    snap.trade_policies = {"paper": {"Import": "TariffsLow", "Export": "TariffsLow"}}
    args = {(d.args["goods"], d.args["side"], d.args["policy"]) for d in trade.candidates(snap)}
    assert ("paper", "Import", "SubventionsLow") in args       # JE 要求进口补贴，不是零关税
    assert ("paper", "Import", "TariffsNone") not in args


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


def test_employment_delta_flags_job_cutting_pms():
    gd = gamedata.get()
    assert production.employment_delta(gd, "pm_mechanized_looms") < 0
    assert production.employment_delta(gd, "pm_automatic_power_looms") < 0
    assert production.employment_delta(gd, "pm_lathe") > 0
    assert production.employment_delta(gd, "pm_mechanized_workshops") > 0


def test_construction_sector_switches_to_iron_frame():
    gd = gamedata.get()
    st = StateRow(1, 1, "首府", 100.0, 10.0, 50, 2_000_000.0, None)
    st.buildings = {"building_construction_sector": _row("building_construction_sector", levels=5)}
    snap = _snap(tag="CHI")
    snap.states = [st]
    snap.prices = {"iron": {"price": 30.0, "base": 40.0},
                   "steel": {"price": 120.0, "base": 100.0}}
    got = production.construction_pm_candidates(gd, snap, set(gd.techs))
    assert got and got[0].args["pm"] == "pm_iron_frame_buildings"


def test_financial_district_stays_privately_owned():
    gd = gamedata.get()
    snap = _snap(tag="CHI")
    s = StateRow(0, 1, "州", 100.0, 10.0, 50, 10_000_000.0, None)
    s.buildings = {"building_financial_district": _row("building_financial_district", levels=5)}
    snap.states = [s]
    got = production.financial_candidates(gd, snap, set(gd.techs))
    assert got and got[0].args["pm"] == "pm_financial_district_privately_owned"


def test_companies_create_capitalist_after_charters():
    snap = _snap(tag="CHI", max_companies=1.0, num_companies=0.0)
    snap.companies = CompanyInfo(available=["company_basic_paper", "company_basic_textiles"], existing=[])
    got = companies.candidates(snap)
    assert got and got[0].args["key"] == "company_basic_paper"   # 攻略：纸张先做过渡
    snap.country["max_companies"] = 0.0                 # corporate_charters 之前没有槽
    assert companies.candidates(snap) == []
    snap.country["max_companies"] = 1.0
    snap.companies.available = ["company_jingdezhen"]   # 官僚/非资本家类别：不建
    assert companies.candidates(snap) == []
    snap.companies.available = ["company_basic_paper"]
    snap.companies.existing = ["company_basic_paper"]
    assert companies.candidates(snap) == []


def test_company_replacement_after_steel_frame():
    snap = _snap(tag="CHI", max_companies=1.0, num_companies=1.0)
    snap.companies = CompanyInfo(available=["company_basic_steel"], existing=["company_basic_paper"])
    snap.date = Date(1862, 1, 1)
    got = companies.candidates(snap)
    assert got and got[0].args == {"key": "company_basic_paper", "create": False}


def test_steel_frame_prebuild_multiplier():
    c = strategy_config.cfg()["construction"]
    assert construction.steel_frame_multiplier(c, {"bessemer_process"}, ["glass"]) > 1.0
    assert construction.steel_frame_multiplier(c, set(), ["glass"]) == 1.0
    assert construction.steel_frame_multiplier(c, {"bessemer_process"}, ["grain"]) == 1.0


def test_construction_rush_slots_override():
    snap = _snap(tag="CHI", queue_government=50.0, construction=22.0, construction_used=22.0)
    st = StateRow(0, 1, "州", 100.0, 10.0, 50, 10_000_000.0, None)
    st.buildings["building_construction_sector"] = _row("building_construction_sector", levels=6)
    snap.states = [st]
    assert construction.slots(snap) >= 8


def test_university_target_dynamic_and_late():
    uni = strategy_config.profile(_snap(tag="CHI")).get("universities")
    assert construction.university_target(_snap(tag="CHI", literacy=0.15), uni) == 23
    assert construction.university_target(_snap(tag="CHI", literacy=0.40), uni) == 60
    late = _snap(tag="CHI", literacy=0.40, money=9_000_000.0, gold_limit=5_000_000.0)
    late.date = Date(1862, 1, 1)
    assert construction.university_target(late, uni) == 100


def test_fallback_route_covers_key_laws():
    route = strategy_config.fallback_route(_snap(tag="CHI"))
    laws = {law for _, law in route}
    assert {"law_tenant_farmers", "law_interventionism", "law_public_schools"} <= laws


def test_law_route_groups_match_laws_json():
    import json
    import os
    from agent.strategy import config as cfgmod
    laws = json.load(open(os.path.join(cfgmod.DATA, "laws.json"), encoding="utf-8"))["laws"]
    for group, law in strategy_config.law_route(_snap(tag="CHI")):
        assert laws[law]["group"] == group, f"{law} 属于 {laws[law]['group']}，路线写成 {group}"


def test_logging_keeps_a_few_hardwood_states():
    gd = gamedata.get()
    snap = _snap(tag="CHI")
    base = gd.base_prices()
    snap.prices = {"wood": {"price": base["wood"]},
                   "hardwood": {"price": base["hardwood"] * 2.0}}   # 2.0× → 4 个硬木州
    snap.states = []
    for i in range(5):
        st = StateRow(i, i + 1, f"林{i}", 100.0, 10.0, 50, 10_000_000.0, None)
        st.buildings["building_logging_camp"] = _row("building_logging_camp", levels=10 - i)
        snap.states.append(st)
    got = production.logging_candidates(gd, snap, set(gd.techs))
    assert len(got) == 3
    assert {d.args["pm"] for d in got} == {"pm_increased_hardwood", "pm_no_hardwood"}


def test_institutions_late_five_levels_when_rich():
    snap = _snap(tag="CHI", money=9_000_000.0, gold_limit=5_000_000.0, balance=10_000.0, tax_waste=0.0)
    snap.institutions = ["教育", "卫生系统"]
    assert institutions.candidates(snap) == [] or all(d.args["level"] == 1 for d in institutions.candidates(snap))
    snap.date = Date(1862, 1, 1)
    got = institutions.candidates(snap)
    assert {d.args["institution"]: d.args["level"] for d in got} == {"教育": 5, "卫生系统": 5}


def test_fragile_unity_guard_skips_distribution_of_power():
    route = [("lawgroup_trade_policy", "law_mercantilism"),
             ("lawgroup_distribution_of_power", "law_oligarchy"),
             ("lawgroup_governance_principles", "law_corporate_state")]
    assert politics.guard_fragile_unity(route, 2) == route
    assert politics.guard_fragile_unity(route, 1) == [("lawgroup_trade_policy", "law_mercantilism")]
    assert politics.guard_fragile_unity(route, None) == route


def test_diplomacy_match_action_by_key_or_chinese_name():
    assert diplomacy.match_action({"action": "trade_privilege", "name": "贸易特权"}, ["trade_privilege"])
    assert diplomacy.match_action({"action": "x", "name": "贸易特权"}, ["贸易特选", "贸易特权"])
    assert diplomacy.match_action({"action": "x", "name": "建立大使馆"}, ["embassy", "大使馆"])
    assert not diplomacy.match_action({"action": "embargo", "name": "禁运"}, ["gift"])


def test_trade_proactive_imports_before_1845():
    snap = _snap(tag="CHI")
    snap.trade_policies = {"wood": {"Import": "TariffsLow", "Export": "TariffsLow"}}
    snap.prices = {"wood": {"buy": 10.0, "sell": 10.0, "price": 100.0, "base": 100.0}}
    got = trade.candidates(snap)
    assert any(d.args == {"goods": "wood", "side": "Import", "policy": "TariffsNone"} for d in got)
    snap.date = Date(1846, 1, 1)
    got = trade.candidates(snap)
    assert not any(d.args.get("policy") == "TariffsNone" for d in got)


def test_trade_late_import_subvention():
    snap = _snap(tag="CHI", balance=10_000.0)
    snap.date = Date(1862, 1, 1)
    snap.trade_policies = {"iron": {"Import": "TariffsNone", "Export": "TariffsLow"}}
    snap.prices = {"iron": {"buy": 160.0, "sell": 100.0, "price": 160.0, "base": 100.0}}
    got = trade.candidates(snap)
    assert any(d.args == {"goods": "iron", "side": "Import", "policy": "SubventionsLow"} for d in got)


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


def test_diplomacy_accepts_113_localized_treaties():
    snap = _snap(tag="CHI")
    assert diplomacy.accept_proposal({"name": "建立大使馆", "actor": "GBR"}, snap)
    # 方向未知的同盟/保障一律不签，避免大清变成保障国被拖入战争
    assert not diplomacy.accept_proposal({"name": "共同防御条约", "actor": "RUS"}, snap)
    assert diplomacy.accept_proposal({"name": "共同防御条约", "actor": "RUS",
                                      "direction": "incoming"}, snap)
    assert diplomacy.accept_proposal({"name": "保证独立", "actor": "FRA",
                                      "direction": "incoming"}, snap)
    assert not diplomacy.accept_proposal({"name": "要求割让香港", "actor": "GBR"}, snap)


def test_diplomacy_rejects_demands_and_sway():
    assert not diplomacy.accept_proposal({"kind": "demand", "name": "割让香港", "actor": "英国"})
    assert not diplomacy.accept_proposal({"kind": "sway", "name": "加入战争", "actor": "法国"})


def test_diplomacy_accepts_defensive_pact_rejects_investment_rights():
    assert diplomacy.accept_proposal({"kind": "treaty", "name": "防御同盟", "actor": "俄国",
                                      "direction": "incoming"})
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


def test_construction_sector_stops_at_200_levels():
    gd = gamedata.get()
    st = StateRow(1, 1, "首府", 100.0, 10.0, 50, 2_000_000.0, None)
    st.buildings = {"building_construction_sector": _row("building_construction_sector", 200)}
    snap = _snap(income=500_000.0, expenses=300_000.0, balance=200_000.0, money=5_000_000.0)
    snap.states = [st]
    assert not [d for d in construction.candidates(gd, snap, set(gd.techs), {})
                if d.args["building"] == "building_construction_sector"]
    st.buildings["building_construction_sector"] = _row("building_construction_sector", 199)
    assert [d for d in construction.candidates(gd, snap, set(gd.techs), {})
            if d.args["building"] == "building_construction_sector"]


def test_sol_recovery_reserves_consumer_slots():
    def dec(key: str) -> construction.Decision:
        return construction.Decision("build", {"state": 0, "building": key}, key, 1.0)

    out = [dec("building_construction_sector"), dec("building_financial_district"),
           dec("building_railway"), dec("building_port")]
    picked = [dec("building_textile_mill"), dec("building_furniture_manufactory"),
              dec("building_steel_mill")]
    low = _snap(sol=7.0)
    got, rest = construction._ensure_consumer_slots(out, picked, 4, low)
    top = [d.args["building"] for d in got[:4]]
    assert "building_textile_mill" in top and "building_furniture_manufactory" in top
    assert [d.args["building"] for d in rest] == ["building_steel_mill"]
    high = _snap(sol=9.0)
    same, rest2 = construction._ensure_consumer_slots(out, picked, 4, high)
    assert [d.args["building"] for d in same] == [d.args["building"] for d in out]
    assert rest2 == picked


def test_input_recovery_reserves_upstream_slots():
    def dec(key: str) -> construction.Decision:
        return construction.Decision("build", {"state": 0, "building": key}, key, 1.0)

    out = [dec("building_construction_sector"), dec("building_financial_district"),
           dec("building_railway"), dec("building_university")]
    picked = [dec("building_iron_mine"), dec("building_steel_mill"),
              dec("building_textile_mill")]
    snap = _snap()
    snap.prices = {"iron": {"buy": 300.0, "sell": 100.0}}
    got, rest = construction._ensure_input_slots(out, picked, 4, snap)
    top = [d.args["building"] for d in got[:4]]
    assert "building_iron_mine" in top
    assert [d.args["building"] for d in rest] == ["building_steel_mill", "building_textile_mill"]
    snap.prices = {"iron": {"buy": 100.0, "sell": 100.0}}
    same, rest2 = construction._ensure_input_slots(out, picked, 4, snap)
    assert [d.args["building"] for d in same] == [d.args["building"] for d in out]
    assert rest2 == picked


def test_recovery_slots_keep_both_input_and_consumer():
    def dec(key: str) -> construction.Decision:
        return construction.Decision("build", {"state": 0, "building": key}, key, 1.0)

    out = [dec("building_construction_sector"), dec("building_financial_district"),
           dec("building_railway"), dec("building_university")]
    picked = [dec("building_iron_mine"), dec("building_steel_mill"),
              dec("building_textile_mill"), dec("building_furniture_manufactory")]
    snap = _snap(sol=7.0)
    snap.prices = {"iron": {"buy": 300.0, "sell": 100.0}}
    got, rest = construction._ensure_recovery_slots(out, picked, 4, snap)
    top = [d.args["building"] for d in got[:4]]
    assert "building_iron_mine" in top and "building_textile_mill" in top
    assert [d.args["building"] for d in rest] == ["building_steel_mill"]


def test_financial_district_expands_when_queueable():
    gd = gamedata.get()
    st = StateRow(1, 1, "金融州", 100.0, 10.0, 50, 8_000_000.0, None)
    row = _row("building_financial_district", 1)
    st.buildings = {"building_financial_district": row}
    snap = _snap(tag="CHI")
    snap.states = [st]
    got = [d for d in construction.candidates(gd, snap, set(gd.techs), {})
           if d.args["building"] == "building_financial_district"]
    assert got and "资本家" in got[0].why
    row.can_queue = False
    assert not [d for d in construction.candidates(gd, snap, set(gd.techs), {})
                if d.args["building"] == "building_financial_district"]
