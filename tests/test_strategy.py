"""策略层单测：构造的局面，不需要游戏。"""

from agent import gamedata
from agent.game import Date
from agent.observe import BuildingRow, LawRow, Snapshot, StateRow
from agent.strategy import budget, construction, politics, research


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


def test_politics_skips_active_laws():
    snap = _snap()
    snap.laws = {"lawgroup_economic_system": LawRow("lawgroup_economic_system", "law_interventionism", "干预主义", [])}
    laws = [d.args["law"] for d in politics.candidates(snap, None)]
    assert "law_interventionism" not in laws and "law_laissez_faire" in laws
    assert politics.candidates(snap, "某法律") == []


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
