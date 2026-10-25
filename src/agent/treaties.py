"""目标法律承诺：真实条约草稿 → 输入条款 → 提案 → 生效条款核验。

与1.13.11界面同一套方法；只读取内存定位真实面板，不写游戏内存。
发送成功只记pending，不能算成法律承诺已生效。
"""
from __future__ import annotations

import re
import struct
import time
from typing import Callable

from agent.actions import Actions, ActionResult, TREATIES
from agent.bridge import Bridge, BridgeError, GameError, PLAYER, PLAYER_MUT, number, plain, FIELD_ERROR
from agent.observe import _name_index

DRAFTS = f"{PLAYER_MUT}.GetDraftTreaties"


class LawCommitments:
    def __init__(self, bridge: Bridge):
        self.b = bridge

    def records(self) -> list[dict]:
        """本国承担的法律承诺，区分草稿/冻结/已生效；重启后也能去重。"""
        own = self.b.read(f"[{PLAYER}.GetTagName]")
        by_name = _name_index("laws")
        out, seen = [], set()
        for source in (TREATIES, DRAFTS):
            fields = ["Treaty.GetNameNoFormatting", "Treaty.IsDraft", "Treaty.IsValid",
                      "Treaty.IsFrozenFor(Treaty.GetFirstCountry.Self)",
                      "Treaty.IsFrozenFor(Treaty.GetSecondCountry.Self)",
                      "Treaty.GetBindingDays", "Treaty.GetBindingDaysLeft"]
            for i, row in enumerate(self.b.rows(source, fields)):
                if any(v.startswith(FIELD_ERROR) for v in row):
                    raise GameError("法律承诺条约状态不可读")
                name, draft, valid, frozen_first, frozen_second, days, left = row
                if valid != "1":
                    continue
                articles = self.b.rows("Treaty.GetAllArticles", [
                    "Article.HasType('law_commitment')", "Article.HasType('money_transfer')",
                    "Article.GetSourceCountry.GetTagName", "Article.GetTargetCountry.GetTagName"], [(source, i)])
                if any(v.startswith(FIELD_ERROR) for a in articles for v in a):
                    raise GameError("法律承诺条款不可读")
                weekly = 0.0
                for ai, a in enumerate(articles):
                    if a[1] == '1' and a[2] == own:
                        weekly += number(self.b.read('[Article.GetQuantity]', [(source, i), ('Treaty.GetAllArticles', ai)])) or 0
                for ai, (law, _, actor, target) in enumerate(articles):
                    if law != "1" or actor != own:
                        continue
                    law_name, unfulfilled = self.b.read_many(['Article.GetLaw.GetNameNoFormatting',
                        'Article.GetNonFulfillmentDesc'], [(source, i), ('Treaty.GetAllArticles', ai)])
                    if law_name is None or unfulfilled is None:
                        raise GameError('法律承诺必填法/履约状态不可读')
                    key = by_name.get(plain(law_name))
                    if not key:
                        raise GameError(f"无法识别承诺法律：{plain(law_name)}")
                    frozen = frozen_first == '1' or frozen_second == '1'
                    status = 'pending' if draft == '1' else 'frozen' if frozen else 'at_risk' if plain(unfulfilled) else 'active'
                    identity = (name, target, key, status)
                    if identity not in seen:
                        seen.add(identity)
                        out.append(dict(name=plain(name), partner=target, law=key, status=status,
                                        weekly=weekly, binding_days=number(days), binding_days_left=number(left),
                                        source=source, index=i, non_fulfillment=plain(unfulfilled),
                                        frozen_first=frozen_first == '1', frozen_second=frozen_second == '1',
                                        simple_transfer=len(articles) == 2 and all(
                                            (a[0] == '1' or a[1] == '1') and a[2:] == [own, target] for a in articles)))
        return out

    def retire_completed(self, active_laws: set[str]) -> ActionResult | None:
        """只退出已完成、已解绑定且没有附带权益/退出惩罚的纯承诺+转账。"""
        for r in self.records():
            if (r['status'] == 'pending' or r['law'] not in active_laws or not r['simple_transfer']
                    or r['binding_days_left'] is None or r['binding_days_left'] > 0):
                continue
            path = [(r['source'], r['index'])]
            name, days, penalty, valid = self.b.read_many(['Treaty.GetNameNoFormatting', 'Treaty.GetBindingDaysLeft',
                f'Treaty.GetWithdrawPenaltiesDesc({PLAYER}.Self)', 'IsValid(Treaty.WithdrawFromTreaty)'], path)
            if (plain(name or '') == r['name'] and number(days or '') == 0 and penalty is not None
                    and not plain(penalty) and valid == '1'):
                return Actions(self.b).withdraw_treaty(r['index'])
        return None

    def _draft_path(self) -> list:
        """每次按RTTI识别面板；不缓存进程地址或硬编码面板下标。"""
        def u64(addr):
            return struct.unpack("<Q", self.b.mem_read(addr, 8))[0]
        bar = struct.unpack_from("<Q", self.b.eval_raw("InformationPanelBar.AccessSelf"), 8)[0]
        header = self.b.mem_read(bar, 24)
        array = struct.unpack_from("<Q", header, 8)[0]
        capacity, size = struct.unpack_from("<II", header, 16)
        if not 0 < size <= capacity <= 128:
            raise GameError("无法识别InformationPanelBar面板数组")
        for ptr in struct.unpack(f"<{size}Q", self.b.mem_read(array, size * 8)):
            try:
                locator = u64(u64(ptr) - 8)
                sig, _, _, type_rva, _, self_rva = struct.unpack("<6I", self.b.mem_read(locator, 24))
                if sig != 1:
                    continue
                name = self.b.mem_read(locator - self_rva + type_rva + 16, 96).split(b"\0")[0]
                if name == b".?AVCTreatyDraftPanel@@":
                    return [(f"=@{ptr:x}", 0), ("=TreatyDraftPanel.GetDraft", 0)]
            except (BridgeError, struct.error):
                continue
        raise GameError("未找到真实TreatyDraftPanel，未发送条约")

    def propose(self, partner: str, law: str, max_weekly: float,
                approve: Callable[[float], bool], binding_days: int = 1825) -> ActionResult:
        """仅在游戏确定接受、条款及预算均通过时发送；approve须重读实时预算。"""
        if not re.fullmatch(r"[A-Z0-9_]{2,12}", partner) or not re.fullmatch(r"law_[a-z0-9_]+", law):
            raise ValueError("国家/法律key不合法")
        if binding_days != 1825 or not 0 <= max_weekly <= 5000:
            raise ValueError("承诺限5年、每周资金转让不超过5000")
        name = f"法律承诺 {law}（{partner}）"
        existing = [r for r in self.records() if r["law"] == law]
        if existing:
            return ActionResult(True, name, "已是存续承诺（含冻结/未履约），不重复付费", existing, existing)
        own = self.b.read(f"[{PLAYER}.GetTagName]")
        ref = [(Actions(self.b).country_ref(partner), 0)]
        self.b.exec(f"InformationPanelBar.OpenTreatyDraftPanelForNewDraft({PLAYER}.Self,Country.Self)", ref)
        path = self._draft_path()
        read = lambda expr: self.b.read(f"[{expr}]", path)
        if (read("TreatyDraft.GetFirstCountry.GetTagName"), read("TreatyDraft.GetSecondCountry.GetTagName")) != (own, partner):
            raise GameError("条约草稿双方不匹配，未发送")
        # 只操作本次新草稿；不在含其他条件的草稿上继续添加条款。
        if any(self.b.rows(f"TreatyDraft.GetSelected{part}", ["ArticleDraft.GetNameNoFormatting"], path)
               for part in ("Offers", "Demands", "MutualAgreements")):
            self.b.exec('InformationPanelBar.ClosePanel')
            return ActionResult(False, name, "新草稿已有其他条款，未覆盖或发送")
        self.b.exec(f"TreatyDraft.SetBindingDays('(int32){binding_days}')", path)
        article = path + [("TreatyDraft.GetSelectedOffers", 0)]
        try:
            self.b.exec_pair(f"TreatyDraft.AddArticle(GetArticleType('law_commitment').Self,{PLAYER}.Self,"
                             "TreatyDraft.GetSecondCountry.Self)",
                             f"ArticleDraft.SetLaw(GetLawType('{law}').Self)", path, article)
        except (GameError, BridgeError):
            self._clear_offers(path)  # 此阶段尚未发送，失败也不遗留空目标法
            raise
        if self.b.read(f"[ArticleDraft.IsLawTypeValidInput(GetLawType('{law}').Self)]", article) != "1":
            self._clear_offers(path)
            return ActionResult(False, name, "对方不支持目标法律或法律前置未满足")
        amount, money = 0.0, None
        for candidate in sorted({0, min(1000, max_weekly), min(2000, max_weekly), min(3200, max_weekly), max_weekly}):
            if candidate > 0:
                if money is None:
                    self.b.exec(f"TreatyDraft.AddArticle(GetArticleType('money_transfer').Self,{PLAYER}.Self,"
                                "TreatyDraft.GetSecondCountry.Self)", path)
                    money = path + [("TreatyDraft.GetSelectedOffers", 1)]
                self.b.exec(f"ArticleDraft.SetQuantity('(CFixedPoint){candidate:g}')", money)
            if read("TreatyDraft.WillAIAccept(TreatyDraft.GetSecondCountry.Self)") == "1":
                amount = candidate
                break
        else:
            self._clear_offers(path)
            return ActionResult(False, name, f"每周资金转让上限{max_weekly:g}内对方仍不确定接受")
        offers = self.b.rows("TreatyDraft.GetSelectedOffers", [
            "ArticleDraft.HasType('law_commitment')", "ArticleDraft.HasType('money_transfer')",
            "ArticleDraft.GetFirstOrSource.GetTagName", "ArticleDraft.GetSecondOrTarget.GetTagName",
            f"ObjectsEqual(ArticleDraft.GetLawType.Self,GetLawType('{law}').Self)",
            "ArticleDraft.GetQuantity", "ArticleDraft.HasAllRequiredInputsSet", "ArticleDraft.IsPossible"], path)
        expected = 2 if amount else 1
        if (len(offers) != expected or not offers or offers[0][:5] != ["1", "0", own, partner, "1"]
                or any(r[6:] != ["1", "1"] for r in offers)
                or (amount and (offers[1][:4] != ["0", "1", own, partner] or number(offers[1][5]) != amount))
                or number(read("TreatyDraft.GetBindingDays")) != binding_days
                or read("IsValid(TreatyDraft.SendProposal)") != "1"
                or any(self.b.rows(f'TreatyDraft.GetSelected{part}', ['ArticleDraft.GetNameNoFormatting'], path)
                       for part in ('Demands', 'MutualAgreements'))):
            self._clear_offers(path)
            raise GameError("条约条款/方向/金额核验失败，未发送")
        if not approve(amount):
            self._clear_offers(path)
            return ActionResult(False, name, f"每周转账{amount:g}未通过实时预算/履约条件")
        self.b.exec("Execute(TreatyDraft.SendProposal)", path)
        # 不再调用SendProposal；超时后也只能检查，不能重发。
        for _ in range(12):
            found = [r for r in self.records() if r["law"] == law and r["partner"] == partner
                     and r["weekly"] == amount and r["binding_days"] == binding_days]
            if found:
                self.b.exec("InformationPanelBar.ClosePanel")
                return ActionResult(True, name, f"{found[0]['status']}，持续转账{amount:g}/周", None, found[0])
            time.sleep(.1)
        return ActionResult(False, name, "已下发但未确认提案；禁止立即重发",
                            None, dict(status="unconfirmed", law=law, partner=partner, weekly=amount))

    def _clear_offers(self, path: list) -> None:
        """只清理本次新建、尚未发送的草稿，退出时不遗留空输入条款。"""
        for _ in range(2):
            if not self.b.rows('TreatyDraft.GetSelectedOffers', ['ArticleDraft.GetNameNoFormatting'], path):
                break
            self.b.exec('TreatyDraft.RemoveArticle(ArticleDraft.Self)', path + [('TreatyDraft.GetSelectedOffers', 0)])
        self.b.exec('InformationPanelBar.ClosePanel')
