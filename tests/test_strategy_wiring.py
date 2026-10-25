from agent import runner, observe
from agent.actions import ActionResult
from agent.observe import LawOption, LawRow
from agent.strategy import budget, construction, politics, plan
from agent import gamedata
from test_strategy import _snap


def option(key, group, valid=True, success=.5, stall=.1):
    return LawOption(group, key, key, [], valid, '' if valid else observe.CHANCE_REQUIREMENT,
                     success, 0, stall, 0, {})


def qing():
    s = _snap(tag='CHI', money=40_000_000, balance=69_000, construction=247,
              construction_used=75, construction_goods=75_000)
    s.laws = {g: LawRow(g, k, k, []) for g, k in [
        ('lawgroup_trade_policy', 'law_isolationism'), ('lawgroup_policing', 'law_no_police'),
        ('lawgroup_land_reform', 'law_serfdom')]}
    return s


def test_reload_unknown_old_cost_does_not_make_construction_free():
    s = qing()
    s.country.update(construction_used=0, construction_goods=0, balance=50_000)
    limit, cost = budget.construction_allowance(s)
    assert limit == 0 and cost > 50_000


def test_large_treasury_cannot_override_negative_flow_or_pending_transfers():
    s = qing()
    s.country['balance'] = -1
    assert budget.construction_allowance(s)[0] == 0
    s.country.update(balance=28_000, reserved_weekly=5000)
    assert budget.construction_allowance(s)[0] == 0
    assert not budget.can_spend(s, weekly=31_000)


def test_new_queue_obeys_allowance_even_with_unused_capacity_and_large_cash():
    s = qing()
    s.country.update(government_queue_limit=1, queue_government=1)
    assert construction.slots(s) == 0
    s.country['queue_government'] = 0
    assert construction.slots(s) == 1


def test_quote_keeps_private_and_government_construction_units_separate():
    s = qing()
    s.country.update(construction_used=100, construction_goods=126_000,
                     government_construction_used=25, government_construction_goods=51_000)
    limit, cost = budget.construction_allowance(s)
    assert limit == 2 and 50_000 < cost < 80_000
    assert limit * cost < s.country['balance'] + s.country['government_construction_goods']
    s.country.update(project_construction_points=50)
    assert budget.construction_allowance(s)[0] == 1


def test_free_points_or_post_pause_recalculation_cannot_make_quote_nearly_free():
    s = qing()
    s.country.update(construction_used=42, construction_goods=5000)
    _, cost = budget.construction_allowance(s)
    assert cost >= 26_250


def test_execution_rejects_extra_projects_from_a_stale_large_plan(monkeypatch):
    s, queue, built = qing(), [], []
    class FakeActions:
        def __init__(self, b): pass
        def construction_queue(self): return list(queue)
    def build(a, d, snap):
        queue.append(dict(index=len(queue), building=d.args['building'], under_construction=False))
        built.append(d)
        return ActionResult(True, 'built')
    monkeypatch.setattr(runner, 'Actions', FakeActions)
    monkeypatch.setattr(runner, '_trim_sector', lambda *a: None)
    monkeypatch.setattr(runner, '_promote_queue', lambda *a: None)
    monkeypatch.setattr(runner, '_do', build)
    monkeypatch.setattr(observe, 'country', lambda b: ('', dict(s.country), '', '', s.date))
    from agent.strategy.config import Decision
    p = plan.Plan(build=[Decision('build', {'building': 'building_tooling_workshop'}) for _ in range(8)],
                  build_slots=8)
    runner.execute(None, p, s, runner.Memory(government_queue_limit=2), lambda _: None)
    assert len(built) == 2


def test_first_trade_law_is_not_displaced_by_easier_police():
    s = qing()
    merc = option('law_mercantilism', 'lawgroup_trade_policy', success=.1, stall=.01)
    police = option('law_dedicated_police', 'lawgroup_policing', success=1, stall=0)
    assert politics.candidates(s, [police, merc], None)[0].args['law'] == merc.key
    merc.valid, merc.why_not, merc.success = False, observe.CHANCE_REQUIREMENT, 0
    assert politics.commitment_target(s, [police, merc]) is merc
    p = plan.decide(gamedata.get(), s, set(), {}, None, law_options=[police, merc])
    assert not p.law  # 先取得承诺，不先推100%的警察法


def test_pending_commitment_reserves_weekly_cost_and_prevents_resend(monkeypatch):
    s = qing()
    merc = option('law_mercantilism', 'lawgroup_trade_policy', False, 0)
    records, calls = [], []
    class Service:
        def __init__(self, b): pass
        def records(self): return records
        def retire_completed(self, laws): return None
        def propose(self, partner, law, maximum, approve, days):
            assert approve(5000)
            calls.append(partner)
            record = dict(name='test', status='pending', law=law, partner=partner, weekly=5000)
            records.append(record)
            return ActionResult(True, 'sent', '', None, record)
    monkeypatch.setattr('agent.treaties.LawCommitments', Service)
    monkeypatch.setattr(runner, 'enacting', lambda b: None)
    monkeypatch.setattr(observe, 'law_options', lambda *a: [merc])
    monkeypatch.setattr(observe, 'country', lambda b: ('', dict(s.country), '', '', s.date))
    mem = runner.Memory()
    assert runner.handle_law_commitment(None, s, mem, lambda _: None)
    assert mem.reserved_weekly == 5000 and calls == ['SPA']
    # 模拟runner重启：不能再付一笔，也必须重建待生效支出预留。
    restarted = runner.Memory()
    assert not runner.handle_law_commitment(None, s, restarted, lambda _: None)
    assert restarted.reserved_weekly == 5000 and calls == ['SPA']


def test_only_verified_active_commitment_relaxes_initial_law_threshold():
    s = qing()
    merc = option('law_mercantilism', 'lawgroup_trade_policy', success=.05, stall=.093)
    merc.advance = .006
    assert politics.candidates(s, [merc], None) == []
    s.country['committed_laws'] = {'law_mercantilism'}
    assert politics.candidates(s, [merc], None)[0].args['law'] == merc.key
    merc.success, merc.advance = 0, 0
    assert politics.candidates(s, [merc], None) == []
    merc.valid = False
    assert politics.candidates(s, [merc], None) == []
