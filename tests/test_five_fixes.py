"""十年实测暴露的回归：现行法、官僚、整军、承诺与小批施工。"""
from agent import gamedata, observe, runner
from agent.bridge import PLAYER
from agent.bridge import Bridge, BridgeError
import pytest
from agent.observe import LawRow, StateRow
from agent.strategy import budget, construction, politics, plan
from agent.treaties import LawCommitments, DRAFTS
from test_strategy import _snap, _row
from test_strategy_wiring import option, qing


def test_law_observation_reads_enacted_law_instead_of_target():
    class Bridge:
        def rows(self, source, fields):
            assert fields[1] == 'Law.GetActiveGroupLaw.GetLawType.GetName'
            return [['lawgroup_land_reform', '农奴制']] if source.endswith(observe.LAW_LISTS[0]) else []
    laws = observe.laws(Bridge())
    assert laws['lawgroup_land_reform'].key == 'law_serfdom'


def test_old_enactment_target_is_not_used_after_enactment_ends():
    class Bridge:
        def read(self, expression):
            assert expression == f'[{PLAYER}.IsEnactingLaw]'
            return '0'
    assert observe.law_progress(Bridge()) is None
    assert runner.enacting(Bridge()) is None


def test_1846_budget_allows_one_project_without_spending_reserves():
    s = qing()
    s.country.update(balance=28209.52, construction=279.94, construction_used=74.99,
                     construction_goods=73193, government_construction_used=0,
                     government_construction_goods=0)
    limit, quote = budget.construction_allowance(s)
    assert limit == 1
    assert s.country['balance'] - quote >= 1000
    s.country.update(reserved_weekly=5000)
    assert budget.construction_allowance(s)[0] == 0
    s.country.update(balance=-1, money=100_000_000)
    assert budget.construction_allowance(s)[0] == 0


def test_national_bureaucracy_recovery_is_not_blocked_by_203_existing_levels(monkeypatch):
    s = qing()
    s.country.update(bureaucracy=-5392, bureaucracy_income=11156,
                     balance=28209.52, government_queue_limit=1)
    st = StateRow(0, 1, '州', 100, 40, 100, 10_000_000, None, unemployed=50000)
    st.buildings[construction.ADMIN] = _row(construction.ADMIN, 203)
    st.buildings[construction.SECTOR] = _row(construction.SECTOR, 61)
    s.states = [st]
    monkeypatch.setitem(construction.cfg()['construction'], 'admin_max_total_levels', 40)
    got = construction.candidates(gamedata.get(), s, set(gamedata.get().techs), {})
    assert got[0].args['building'] == construction.ADMIN
    assert got[0].args['operating_weekly'] >= 1000
    st.infrastructure_usage = 99
    assert not construction.bureaucracy_projects(s)


def test_intervention_enactment_prepares_for_loss_of_traditionalism_discount():
    s = qing()
    s.laws['lawgroup_economic_system'] = LawRow('lawgroup_economic_system', 'law_traditionalism', '', [])
    s.country.update(bureaucracy=500, bureaucracy_income=12000, institutions=0)
    plan.decide(gamedata.get(), s, set(), {}, 'law_interventionism')
    assert s.country['bureaucracy_target'] > 4000


def test_new_police_institution_requires_bureaucracy_before_enactment():
    s = qing()
    police = option('law_dedicated_police', 'lawgroup_policing', success=1)
    s.country.update(bureaucracy=100, institution_level_cost=-3975)
    assert politics.institution_block(s, police)
    assert not politics.candidates(s, [police], None, fallback=True)
    s.country['bureaucracy'] = 5000
    assert not politics.institution_block(s, police)
    assert politics.candidates(s, [police], None)


def test_peaceful_opening_does_not_recruit_50_new_artillery():
    s = qing()
    s.country.update(bureaucracy=5000, rank_name='未受认可的主要政权')
    assert not runner.regular_recruitment_allowed(s, False)
    assert runner.regular_recruitment_allowed(s, True)
    s.date = observe.Date(1846, 1, 1)
    assert not runner.regular_recruitment_allowed(s, False)
    s.country['rank_name'] = '主要政权'
    assert runner.regular_recruitment_allowed(s, False)
    s.country['balance'] = -1
    assert not runner.regular_recruitment_allowed(s, True)


def test_frozen_obligation_with_real_support_can_be_fulfilled():
    s = qing()
    s.laws['lawgroup_economic_system'] = LawRow('lawgroup_economic_system', 'law_traditionalism', '', [])
    opt = option('law_interventionism', 'lawgroup_economic_system', success=.1, stall=.272)
    assert not politics.candidates(s, [opt], None)
    s.country['obligated_laws'] = {opt.key}
    assert politics.candidates(s, [opt], None)[0].args['law'] == opt.key
    opt.success = 0
    assert not politics.candidates(s, [opt], None)


def test_six_month_fallback_is_not_filtered_to_unavailable_commitment():
    s = qing()
    merc = option('law_mercantilism', 'lawgroup_trade_policy', valid=False, success=0)
    tenant = option('law_tenant_farmers', 'lawgroup_land_reform', success=.6, stall=.1)
    p = plan.decide(gamedata.get(), s, set(), {}, None, law_options=[merc, tenant], law_stall=6)
    assert p.law and p.law[0].args['law'] == tenant.key


def test_partner_frozen_is_not_reported_active_and_only_law_reads_law_inputs():
    class Bridge:
        def read(self, expr, path=None):
            if path is None:
                return 'CHI'
            assert path[-1][1] == 1 and expr == '[Article.GetQuantity]'
            return '5000'
        def rows(self, source, fields, path=None):
            if source == DRAFTS:
                return []
            if path is None:
                return [['合同', '0', '1', '0', '1', '1825', '1000']]
            assert 'Article.GetLaw.GetNameNoFormatting' not in fields
            return [['1', '0', 'CHI', 'PRU'], ['0', '1', 'CHI', 'PRU']]
        def read_many(self, fields, path):
            assert path[-1][1] == 0
            return ['经济干预', '未履约26次']
    record = LawCommitments(Bridge()).records()[0]
    assert record['status'] == 'frozen' and record['frozen_second']
    assert record['weekly'] == 5000 and record['non_fulfillment']


def test_bound_completed_contract_is_never_withdrawn(monkeypatch):
    service = LawCommitments(None)
    monkeypatch.setattr(service, 'records', lambda: [dict(status='active', law='law_mercantilism',
                          simple_transfer=True, binding_days_left=1)])
    assert service.retire_completed({'law_mercantilism'}) is None


@pytest.mark.parametrize('days,penalty,simple,withdraw', [(0, '', True, True),
    (1, '', True, False), (0, 'penalty', True, False), (0, '', False, False), (None, '', True, False)])
def test_completed_contract_cleanup_checks_binding_penalties_and_extra_rights(monkeypatch, days, penalty, simple, withdraw):
    from agent.actions import Actions, ActionResult
    class TreatyBridge:
        def read_many(self, fields, path):
            return ['合同', '0', penalty, '1']
    svc = LawCommitments(TreatyBridge())
    monkeypatch.setattr(svc, 'records', lambda: [dict(name='合同', law='law_mercantilism',
        status='active', simple_transfer=simple, binding_days_left=days, source='treaties', index=0)])
    called = []
    monkeypatch.setattr(Actions, 'withdraw_treaty', lambda self, idx: called.append(idx) or ActionResult(True, 'withdraw'))
    r = svc.retire_completed({'law_mercantilism'})
    assert bool(r) == withdraw and called == ([0] if withdraw else [])


def test_pair_transport_carries_distinct_late_resolved_path(monkeypatch):
    b = Bridge()
    calls = []
    monkeypatch.setattr(b, '_request', lambda method, route, params: calls.append((route, params)) or {'ok': True})
    b.exec_pair('add', 'set_law', [('=Draft', 0)], [('=Draft', 0), ('SelectedOffers', 0)])
    assert calls == [('/data/exec_pair', {'stmt': 'add', 'next_stmt': 'set_law', 'p0': '=Draft',
        'i0': 0, 'np0': '=Draft', 'ni0': 0, 'np1': 'SelectedOffers', 'ni1': 0})]


def test_old_bridge_never_falls_back_to_empty_clause_creation(monkeypatch):
    b = Bridge()
    calls = []
    def reject(method, route, params):
        calls.append(route)
        raise BridgeError('404 unknown route')
    monkeypatch.setattr(b, '_request', reject)
    with pytest.raises(BridgeError):
        b.exec_pair('add', 'set_law', [], [])
    assert calls == ['/data/exec_pair']
