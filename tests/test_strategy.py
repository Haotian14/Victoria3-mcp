"""策略层单测：构造的局面，不需要游戏。"""

from agent import gamedata
from agent.game import Date
from agent.observe import BuildingRow, IGRow, LawOption, LawRow, Snapshot, StateRow
from agent.strategy import budget, construction, decrees, diplomacy, events, institutions, politics, research


def _snap(**country) -> Snapshot:
    base = {"money": 1_000_000.0, "gold_limit": 5_000_000.0, "income": 100_000.0, "expenses": 90_000.0,
            "balance": 10_000.0, "construction": 20.0, "construction_used": 20.0, "queue_government": 0.0,
            "tax_waste": 0.0}
    base.update(country)
    return Snapshot(date=Date(1836, 1, 1), name="测试", country=base, tax_level="Medium", researching=None,
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


def test_research_resolves_prerequisites_first():
    gd = gamedata.get()
    cands = research.candidates(gd, set(), None)
    order = [d.args["tech"] for d in cands]
    # 车床需要轧棉机，轧棉机需要制造厂：前置排在前面
    assert order.index("manufacturies") < order.index("cotton_gin") < order.index("lathe")
    assert research.candidates(gd, set(), "lathe") == []


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


def test_event_policy_prefers_good_effects():
    ev = _event("generic.1",
                {"option": 0, "text": "改革", "desc": "增加 10% 创新，减少 5 生活水平",
                 "enabled": True, "default": False},
                {"option": 1, "text": "维持", "desc": "增加激进派，减少征税能力", "enabled": True, "default": True})
    assert events.score(ev, ev["options"][0]) > events.score(ev, ev["options"][1])
    assert events.pick(ev, "CHI") == 0


def test_institutions_follow_profile_and_wait_for_bureaucracy():
    snap = _snap(tag="CHI", tax_waste=0.0)
    assert [d.args["institution"] for d in institutions.candidates(snap)] == ["教育"]
    snap.country["tax_waste"] = 0.3
    assert institutions.candidates(snap) == []


def test_decrees_pick_big_and_overused_states():
    snap = _snap(tag="CHI")
    big = StateRow(0, 1, "大州", 100.0, 120.0, 50, 20_000_000.0, None)
    small = StateRow(1, 2, "小州", 100.0, 10.0, 50, 5_000_000.0, None)
    snap.states = [big, small]
    got = {(d.args["state"], d.args["decree"]) for d in decrees.candidates(snap)}
    assert got == {(1, "促进社会流动"), (1, "道路养护")}


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
