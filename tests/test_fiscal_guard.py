"""财政死亡螺旋回归：现金、已有队列、冷却锁及事件不能绕过护栏。"""
import pytest

from agent import gamedata, runner
from agent.actions import ActionResult
from agent.strategy import budget, construction, events, plan, subsidies
from agent.strategy.config import Decision
from test_strategy import _row, _snap
from agent.observe import StateRow
from agent import observe


@pytest.mark.parametrize("change", [
    {"balance": -1, "money": 100_000_000},
    {"money": 700_000},  # 小于八周支出，仍为盈余
    {"money": 0, "balance": -1, "credit_left": 100_000_000},
    {"in_default": True},
    {"bankrupt": True},
    {"loan_penalty": True},
    {"money": None},
])
def test_emergency_cannot_be_overridden_by_rush_or_priority_fallback(change):
    snap = _snap(tag="CHI", **change)
    st = StateRow(0, 1, "州", 100, 10, 50, 10_000_000, None)
    st.buildings[construction.SECTOR] = _row(construction.SECTOR, 6)
    snap.states = [st]
    gd = gamedata.get()
    assert construction.slots(snap) == 0
    assert construction.candidates(gd, snap, set(gd.techs), {}) == []
    p = plan.decide(gd, snap, set(gd.techs), {}, None)
    assert p.build_slots == 0 and not p.build


def test_emergency_subsidies_cover_unincorporated_and_protected_and_all_rows():
    snap = _snap(tag="CHI", balance=-1)
    for i in range(8):
        st = StateRow(i, i, "州", 100, 10, 50, 10_000_000, None, incorporated=False)
        row = _row("building_railway", 1)
        row.subsidized, row.subsidy_cost = True, 1000
        st.buildings[row.key] = row
        snap.states.append(st)
    got = subsidies.candidates(snap)
    assert len(got) == 8 and all(d.args["on"] is False for d in got)


def test_paused_surplus_does_not_resume_unaffordable_construction(monkeypatch):
    called = []
    class FakeActions:
        def __init__(self, b): pass
        def construction_queue(self):
            return [dict(index=i, under_construction=False) for i in range(4 - len([x for x in called if isinstance(x, int)]))]
        def cancel_construction(self, index):
            called.append(index)
            return ActionResult(True, str(index))
        def country_command(self, cmd):
            called.append(cmd)
            return ActionResult(True, cmd)
    monkeypatch.setattr(runner, "Actions", FakeActions)
    snap = _snap(credit_left=1_000_000, in_default=False, army_size=200, money=40_000_000,
                 construction_paused=True, construction=247, construction_used=75,
                 construction_goods=75_000, balance=10_000)
    mem = runner.Memory(resume_construction_cost=141_450)
    runner.fiscal_guard(None, snap, mem, lambda _: None)
    assert not called
    snap.country["balance"] = 69_000
    runner.fiscal_guard(None, snap, mem, lambda _: None)
    assert called == [3, 2, "ResumeConstruction"]
    assert mem.government_queue_limit == 2


def test_emergency_pauses_existing_queue(monkeypatch):
    called = []
    class FakeActions:
        def __init__(self, b): pass
        def country_command(self, cmd):
            called.append(cmd)
            return ActionResult(True, cmd)
    monkeypatch.setattr(runner, "Actions", FakeActions)
    snap = _snap(credit_left=1_000_000, in_default=False, army_size=411,
                 construction_paused=False, balance=-1000, government_construction_goods=30_000)
    mem = runner.Memory()
    runner.fiscal_guard(None, snap, mem, lambda _: None)
    assert called == ["PauseConstruction"] and mem.resume_construction_cost == 30_000


def test_low_legitimacy_never_raises_even_to_tax_floor():
    for level in ("VeryLow", "Low", "Medium"):
        snap = _snap(tax_level=level, tag="CHI", legitimacy=59, balance=-1_000_000)
        assert budget.decide(snap) is None
        assert budget.action_block(snap, Decision("set_tax", {"level": "High"}))


def test_qing_fiscal_diagnosis_never_funds_deficit_with_high_tax():
    snap = _snap(tag="CHI", legitimacy=100, balance=-50_000, money=500_000)
    assert budget.decide(snap) is None
    assert budget.action_block(snap, Decision("set_tax", {"level": "High"}))
    snap.tax_level = "High"
    assert budget.decide(snap).args['level'] == 'Medium'


def test_execute_guard_blocks_credit_subventions_and_government_pm():
    snap = _snap(balance=-1, money=100_000_000)
    for d in [Decision("build"), Decision("subsidy", {"on": True}),
              Decision("set_institution"), Decision("trade_policy", {"policy": "SubventionsMax"}),
              Decision("set_pm", {"building": "building_construction_sector"}),
              Decision("take_loan"), Decision("start_revolution")]:
        assert budget.action_block(snap, d, 4)
    assert not budget.action_block(snap, Decision("subsidy", {"on": False}), 4)


def test_expensive_event_hard_preference_cannot_override_cash_guard():
    snap = _snap(money=1_000_000)
    opts = [dict(option=0, enabled=True, text="支付 £2,000,000 换推进", desc=""),
            dict(option=1, enabled=True, text="借款", desc=""),
            dict(option=2, enabled=True, text="暂缓", desc="")]
    assert events.pick({"key": "law_test", "options": opts}, "CHI", snap, 4) == 2
    assert events.pick({"options": opts[:2]}, "CHI", snap, 4) is None


def test_loan_penalty_description_does_not_exempt_borrowing():
    snap = _snap(money=100_000_000)
    assert not events.fiscal_option_allowed(dict(text='借款，失去1点统一', desc=''), snap, 4)
    assert events.fiscal_option_allowed(dict(text='偿还贷款，减少债务', desc=''), snap, 4)
    assert not events.fiscal_option_allowed(dict(text='发动革命，降低合法性', desc=''), snap, 4)
    assert not budget.can_spend(snap, weekly=20_000)


def test_unity_progress_read_before_first_plan():
    j = {"journal_entries": [{"key": "je_warlord_china", "progress_value": "4", "bars": []}]}
    assert runner.fragile_points(j) == 4


@pytest.mark.parametrize("group,expected", [("0", "infantry"), ("1", "artillery"), ("2", "cavalry")])
def test_actual_group_ids_are_numeric(group, expected):
    class Bridge:
        def rows(self, lst, fields, path=None):
            return [["军团"]] if path is None else [["类型", group, "20", "21", "0", "2"]]
    rows = observe.army_entries(Bridge())
    assert rows[0]["group"] == expected and rows[0]["expected_regular"] == 21


def test_unmapped_group_fails_closed():
    class Bridge:
        def rows(self, lst, fields, path=None):
            return [["军团"]] if path is None else [["类型", "99", "20", "20", "0", "0"]]
    with pytest.raises(observe.GameError, match="未知军队分组"):
        observe.army_entries(Bridge())
