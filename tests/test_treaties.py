"""条约流程的拒绝/去重/持续支出与真实面板定位，不需要游戏。"""
import struct

import pytest

from agent.actions import Actions
from agent.bridge import BridgeError, GameError
from agent.treaties import LawCommitments


class DraftBridge:
    def __init__(self):
        self.executed = []
        self.offers = []
        self.amount = 0
        self.sent = False
        self.wrong_direction = False

    def read(self, text, path=None):
        expr = text[1:-1]
        values = {
            'GetMetaPlayer.GetPlayedOrObservedCountry.GetTagName': 'CHI',
            'TreatyDraft.GetFirstCountry.GetTagName': 'CHI',
            'TreatyDraft.GetSecondCountry.GetTagName': 'SPA',
            'TreatyDraft.GetBindingDays': '1825',
            "ArticleDraft.IsLawTypeValidInput(GetLawType('law_mercantilism').Self)": '1',
            'TreatyDraft.WillAIAccept(TreatyDraft.GetSecondCountry.Self)': str(int(self.amount >= 4000)),
            'IsValid(TreatyDraft.SendProposal)': '1',
        }
        return values[expr]

    def rows(self, source, fields, path=None):
        if source in ('TreatyDraft.GetSelectedDemands', 'TreatyDraft.GetSelectedMutualAgreements'):
            return []
        assert source == 'TreatyDraft.GetSelectedOffers'
        if len(fields) == 1:
            return [[s] for s in self.offers]
        return [[str(int(s == 'law')), str(int(s == 'money')),
                 'SPA' if self.wrong_direction else 'CHI', 'SPA', str(int(s == 'law')),
                 str(self.amount if s == 'money' else 0), '1', '1'] for s in self.offers]

    def exec(self, cmd, path=None):
        self.executed.append(cmd)
        if "GetArticleType('law_commitment')" in cmd:
            self.offers.append('law')
        elif "GetArticleType('money_transfer')" in cmd:
            self.offers.append('money')
        elif 'SetQuantity' in cmd:
            self.amount = float(cmd.split('CFixedPoint)')[1].split("'")[0])
        elif cmd == 'Execute(TreatyDraft.SendProposal)':
            self.sent = True
        elif cmd == 'TreatyDraft.RemoveArticle(ArticleDraft.Self)':
            self.offers.pop(0)

    def exec_pair(self, stmt, next_stmt, path, next_path):
        self.exec(stmt, path)
        self.exec(next_stmt, next_path)


@pytest.fixture
def deal(monkeypatch):
    b = DraftBridge()
    service = LawCommitments(b)
    monkeypatch.setattr(Actions, 'country_ref', lambda self, tag: '=test_country')
    monkeypatch.setattr(service, '_draft_path', lambda: [])
    monkeypatch.setattr(service, 'records', lambda: [dict(status='pending', law='law_mercantilism',
        partner='SPA', weekly=b.amount, binding_days=1825)] if b.sent else [])
    return b, service


def test_send_is_pending_and_weekly_cost_is_checked_before_send(deal):
    b, service = deal
    approved = []
    r = service.propose('SPA', 'law_mercantilism', 5000, lambda n: approved.append(n) or True)
    assert r.ok and r.after['status'] == 'pending'
    assert approved == [5000] and b.amount == 5000
    assert b.executed.count('Execute(TreatyDraft.SendProposal)') == 1


def test_unaffordable_weekly_payment_never_sends(deal):
    b, service = deal
    r = service.propose('SPA', 'law_mercantilism', 5000, lambda _: False)
    assert not r.ok and not b.sent
    assert not b.offers


def test_low_transfer_ceiling_never_sends_uncertain_acceptance(deal):
    b, service = deal
    r = service.propose('SPA', 'law_mercantilism', 3200, lambda _: True)
    assert not r.ok and not b.sent and b.amount <= 3200


def test_pending_survives_new_service_instance_without_duplicate_send(deal, monkeypatch):
    b, service = deal
    assert service.propose('SPA', 'law_mercantilism', 5000, lambda _: True).ok
    restarted = LawCommitments(b)
    monkeypatch.setattr(restarted, 'records', service.records)
    before = list(b.executed)
    assert restarted.propose('SPA', 'law_mercantilism', 5000, lambda _: True).ok
    assert b.executed == before


def test_wrong_clause_direction_never_sends(deal):
    b, service = deal
    b.wrong_direction = True
    with pytest.raises(GameError, match='方向'):
        service.propose('SPA', 'law_mercantilism', 5000, lambda _: True)
    assert not b.sent


def test_unconfirmed_send_is_never_retried_in_same_call(deal, monkeypatch):
    b, service = deal
    monkeypatch.setattr(service, 'records', lambda: [])
    monkeypatch.setattr('agent.treaties.time.sleep', lambda _: None)
    r = service.propose('SPA', 'law_mercantilism', 5000, lambda _: True)
    assert not r.ok and r.after['status'] == 'unconfirmed'
    assert b.executed.count('Execute(TreatyDraft.SendProposal)') == 1


def test_panel_is_found_by_rtti_after_array_index_changes():
    memory = {
        (0x1000, 24): struct.pack('<QQII', 0x1000, 0x2000, 2, 2),
        (0x2000, 16): struct.pack('<QQ', 0x3000, 0x4000),
        (0x4000, 8): struct.pack('<Q', 0x5000),
        (0x4ff8, 8): struct.pack('<Q', 0x6000),
        (0x6000, 24): struct.pack('<6I', 1, 0, 0, 0x100, 0, 0x5000),
        (0x1110, 96): b'.?AVCTreatyDraftPanel@@\0'.ljust(96, b'\0'),
    }
    class MemoryBridge:
        def eval_raw(self, expr): return struct.pack('<QQ', 0, 0x1000)
        def mem_read(self, addr, n):
            try: return memory[(addr, n)]
            except KeyError: raise BridgeError('unreadable')
    assert LawCommitments(MemoryBridge())._draft_path()[0] == ('=@4000', 0)


def test_pair_second_step_failure_cleans_partial_clause_and_never_sends(deal, monkeypatch):
    b, service = deal
    def fail(stmt, next_stmt, path, next_path):
        b.exec(stmt, path)
        raise GameError('second step failed')
    monkeypatch.setattr(b, 'exec_pair', fail)
    with pytest.raises(GameError, match='second step'):
        service.propose('SPA', 'law_mercantilism', 5000, lambda _: True)
    assert not b.offers and not b.sent


def test_preexisting_user_draft_is_not_cleared_or_sent(deal):
    b, service = deal
    b.offers = ['user_clause']
    r = service.propose('SPA', 'law_mercantilism', 5000, lambda _: True)
    assert not r.ok and b.offers == ['user_clause'] and not b.sent
