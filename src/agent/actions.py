"""玩家动作：docs/actions.md 清单里的游戏命令。

全部走界面按钮背后的同一条命令（Execute(...)），与玩家点击等价：法律要走推行流程、
建造进建造队列、研究进研究槽，不直接改游戏状态。每个动作：
1. 前置：IsValid(命令)，不可用时附上游戏给的原因（GetDesc）；
2. 执行；
3. 后验：再读一次，确认真的生效（命令是异步的，下一帧才落地，最多等一小会）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

from agent import gamedata
from agent.bridge import IGS, PLAYER, PLAYER_MUT, Bridge, GameError, number, plain
from agent.observe import STATES, TAX_LEVELS, Snapshot, _name_index, interest_groups

PM_GROUPS = "Building.AccessProductionMethodGroups"
PM_OPTIONS = "ProductionMethodGroup.AccessBuildingProductionMethods(Building.Self)"
LAW_ALTERNATIVES = "Law.GetLawAlternatives"

LEVELS = TAX_LEVELS
LEVEL_NAMES = {"TaxLevel": "税率", "GovernmentWageLevel": "政府工资", "MilitaryWageLevel": "军队工资",
               "SupplyShipConstructionLevel": "补给舰建造"}
TRADE_POLICIES = ("TariffsNone", "TariffsLow", "TariffsHigh", "TariffsMax",
                  "SubventionsLow", "SubventionsHigh", "SubventionsMax")
# 国家命令 → 核实用的读数
COUNTRY_COMMANDS = {
    "MobilizeAllArmies": "IsMobilized", "DemobilizeAllArmies": "IsMobilized",
    "PauseConstruction": "IsConstructionPaused", "ResumeConstruction": "IsConstructionPaused",
    "PauseShipConstruction": "IsShipConstructionPaused", "ResumeShipConstruction": "IsShipConstructionPaused",
    "DeclareBankruptcy": "InDefault", "LeavePowerBloc": "IsInPowerBloc",
}
COMPANY_TYPES = f"{PLAYER_MUT}.GetAvailableCompanies"
COMPANIES = f"{PLAYER_MUT}.GetCompanies"
CHARTER_TYPES = "GetCompanyCharterTypes"
CHARTER_PROBES = ["Company.HasAnyTradeCharterActive", "Company.HasAnyIndustryCharterActive",
                  "Company.HasAnyInvestmentCharterActive", "Company.HasAnyMonopolyCharterActive",
                  "Company.HasAnyColonizationCharterActive"]

# 事件：每个事件作为上下文求的字段（最后一项判断是不是玩家的事件）
EVENT_FIELDS = ["Event.GetKey", "Event.GetTitle", "Event.GetNumRemainingDays",
                "Event.GetTopScope.GetRootScope.GetCountry.IsLocalPlayer"]
EVENT_OPTIONS = "EventWindow.GetOptions"
OPTION_FIELDS = ["EventOption.GetText", "EventOption.IsEnabled", "EventOption.IsDefaultOption",
                 "EventOption.GetDesc"]
SIGNATURE_FIELDS = ["GetGoldReserves", "GetPrestige", "GetGovernmentLegitimacy", "GetLawBeingEnacted.GetLawType.GetName",
                    "IsEnactingLaw", "IsNegotiating"]   # 谈判事件答完 IsNegotiating 立刻变 0
_ANSWERED: dict[int, int] = {}      # 本进程已回答的事件 id → 选项

JOURNAL = f"{PLAYER_MUT}.AccessActiveJournalEntries"
JOURNAL_FIELDS = ["JournalEntry.GetType.GetKey", "JournalEntry.GetName", "JournalEntry.GetProgressDesc",
                  "JournalEntry.HasProgressBar", "JournalEntry.GetGoalProgressValue",
                  "JournalEntry.GetGoalProgressPercent", "JournalEntry.GetTotalGoalValue",
                  "JournalEntry.GetTimeoutDaysLeft", "JournalEntry.IsProgressing",
                  "JournalEntry.CanComplete", "JournalEntry.GetGoalDesc"]
JE_BUTTONS = "JournalEntry.GetScriptedButtons"      # 只含可见的按钮
JE_BARS = "JournalEntry.GetScriptedProgressBars"    # 脚本进度条（如“赢得认可 0/200”）
BUTTON_CMD = "ScriptedButton.ExecuteEffect"
DECISIONS = f"{PLAYER_MUT}.GetDecisions"
DECISION_CMD = f"Decision.TakeDecision({PLAYER})"

INSTITUTIONS = f"{PLAYER_MUT}.AccessInstitutions"
INSTITUTION_LEVELS = "Institution.AccessInvestmentLevels"
MOVEMENTS = f"{PLAYER_MUT}.AccessPoliticalMovements"
AMENDMENTS = "Law.GetAllAmendments"
SUBJECTS = f"{PLAYER_MUT}.GetSubjects"
# 建筑命令 → 核实读数（PMS = 各方式组的现行生产方式）
BUILDING_COMMANDS = {
    "CancelConstruction": "Building.GetExpansionLevelsInQueue",
    "Downsize": "Building.GetTotalLevels",
    "Nationalize": "Building.GetNumLevelsCanBeNationalized",
    "PauseConstructionOutput": "Building.IsConstructionOutputPaused",
    "ResumeConstructionOutput": "Building.IsConstructionOutputPaused",
    "ToggleAutoExpand": "Building.IsAutoExpanding",
    "ToggleAutoExpandOn": "Building.IsAutoExpanding",
    "ToggleAutoExpandOff": "Building.IsAutoExpanding",
    "TogglePrivatization": "Building.CanBePrivatized",
    "ToggleSubsidies": "Building.IsSubsidized",
    "ToggleSubsidiesOn": "Building.IsSubsidized",
    "ToggleSubsidiesOff": "Building.IsSubsidized",
    "ResetProductionMethodsToStandard": "PMS",
    # 按类型恢复：作用于全国该类建筑，全部恢复后命令变为不可用（「所有生产方式都已调整为国家标准」）
    "GetBuildingType.ResetProductionMethodsToStandard": "IsValid(Building.GetBuildingType.ResetProductionMethodsToStandard)",
    "GetBuildingType.ToggleMonopoly": "Building.GetBuildingType.HasCountryMonopoly",
}
CONSTRUCTION_SPEEDS = "AccessConstructionSpeeds"      # 建造部门的生产方式（全局列表）
# 州命令 → 核实读数（并入要几个月：命令下去后读「正在并入」；对正在并入的州「取消并入」是停下并入）
_INCORPORATION = ["State.IsIncorporated", "State.IsIncorporating"]
STATE_COMMANDS = {
    "IncorporateState": _INCORPORATION, "UnincorporateState": _INCORPORATION,
    "TogglePauseColonization": ["State.IsColonizationPaused"], "AbandonColony": ["State.IsGrowingColony"],
}
DIPLO_ACTION_LISTS = [f"Get{k}{g}DiploActions" for g in ("General", "Overlord", "Subject", "PowerBlocLeader",
                                                          "PowerBlocMember") for k in ("Available", "Potential")]
_TAG_REGION: dict[str, str] = {}    # 国家 tag → 它拥有的一个地区（按值取国家用）
PLAYS = f"{PLAYER_MUT}.AccessActiveDiplomaticPlays"
WARS = f"{PLAYER_MUT}.AccessWars"
TREATIES = f"{PLAYER_MUT}.GetInForceTreaties"
PEACE_FIELDS = ["War.HasActivePeaceDeal", "War.HasActiveWhitePeaceDeal", "War.GetCountryProposingPeace.GetTagName",
                "War.GetDaysUntilPeaceDealFails"]
# 提议：伪造的 TopFrontend（+0x30 是提议数组，读的时候游戏自己重建）
TOP_FRONTEND = "0:30:a=0"
PROPOSALS = "TopFrontend.AccessProposals"
PROPOSAL_KINDS = ("treaty", "action", "demand", "sway")
PROPOSAL_FIELDS = ["Proposal.GetName", "Proposal.GetActor.GetNameNoFormatting", "Proposal.GetTreaty.IsValid",
                   "Proposal.GetDiplomaticAction.GetType.GetKey", "Proposal.GetDiplomaticDemand.IsValid",
                   "Proposal.GetDiplomaticPlay.IsValid"]


def _proposal_kind(flags: list[str]) -> str:
    """提议种类：条约 / 外交行动 / 外交要求 / 拉拢，按 PROPOSAL_FIELDS 后四格哪一项有效判断。"""
    for kind, v in zip(PROPOSAL_KINDS, flags):
        if v and not v.startswith("\x01") and v != "0":
            return kind
    return "?"
_SWAY = "Proposal.GetDiplomaticPlay.GetIncomingSway(Proposal.GetActor.Self,Proposal.GetRecipient.Self)"
PROPOSAL_COMMANDS = {   # 种类 → (接受, 拒绝)，与 popups.gui 里的写法一致
    "treaty": ("Proposal.GetTreaty.AcceptTreatyProposal", "Proposal.GetTreaty.DeclineTreatyProposal"),
    "action": ("Proposal.GetDiplomaticAction.AcceptActionProposal", "Proposal.GetDiplomaticAction.DeclineActionProposal"),
    "demand": ("Proposal.GetDiplomaticDemand.AcceptDiplomaticDemand",
               "Proposal.GetDiplomaticDemand.RejectDiplomaticDemand"),
    "sway": (f"{_SWAY}.AcceptSway", f"{_SWAY}.RejectSway"),
}
PLAY_STANCES = ("Yield", "DeclareNeutrality", "BeOnTheFence", "LeanTowardsInitiator", "LeanTowardsTarget",
                "SupportInitiator", "SupportTarget", "SwitchSide")
PLAY_SIDES = ("IsInitiatorOrBacker", "IsTargetOrBacker", "IsInitiatorLeaning", "IsTargetLeaning", "IsOnTheFence",
              "IsCommittedParticipant", "IsInvolved")
# 外交行动的核实：协定是否生效、还能否再发、原因、两国关系（一次性的行动如驱逐外交官看关系与可用性）
DIPLO_PROBES = ["DiplomaticAction.IsActivePact", "IsValid(DiplomaticAction.ExecuteAction)",
                "GetDesc(DiplomaticAction.ExecuteAction)", f"{PLAYER}.GetRelationsWith(Country.Self)"]
GOV_QUEUE = f"{PLAYER_MUT}.AccessGovernmentConstructionQueue"
PRIVATE_QUEUE = f"{PLAYER_MUT}.AccessPrivateConstructionQueue"
QUEUE_FIELDS = ["ConstructionQueueElement.GetBuilding.GetBuildingType.GetKey",
                "ConstructionQueueElement.GetState.GetNameNoFormatting",
                "ConstructionQueueElement.GetWeeksLeft", "ConstructionQueueElement.IsCurrentlyUnderConstruction"]
LAW_LISTS = ("AccessActivePowerStructureLaws", "AccessActiveEconomyLaws", "AccessActiveHumanRightsLaws",
             "AccessActiveOtherLaws")


def _event_window(event_id: int) -> str:
    """伪造的事件窗口（EventWindow）：+0x88 指向事件句柄（+0x10 是事件 id），+0x110 是选项数组。
    0 号缓冲区就是窗口，1 号是句柄。"""
    return f"0:88:q=b1;0:110:a=0;1:10:i={event_id}"


def _diplo_window(k: int) -> str:
    """伪造的外交行动确认窗口（DiplomaticActionWindow，构造函数 1.13.11 的 021bd860）：
    +0xd8 / +0xdc 两国 id（外交行动对象 +0x10 / +0x14），+0xe0 / +0xe4 选的州（-1 = 不选），+0xe8 标记 1，
    +0xf0 外交行动类型指针（对象 +0x28），+0xf8 义务（0 = 不动用 / 不承诺），+0xfc 2。
    ExecuteAction（021caac0 → 021be590）只读这几项组装 CExecuteDiplomaticActionCommand。k 是外交行动在路径里的下标。"""
    return (f"0:d8:i=c{k}@10;0:dc:i=c{k}@14;0:e0:i=-1;0:e4:i=-1;0:e8:b=1;0:f0:q=c{k}@28;"
            f"0:f8:i=0;0:fc:i=2")


FORMABLE = f"{PLAYER_MUT}.AccessFormableCountries"
BLOC = f"{PLAYER_MUT}.AccessPowerBloc"
ARMIES = f"{PLAYER_MUT}.GetMilitaryFormationsArmy"
FLEETS = f"{PLAYER_MUT}.GetMilitaryFormationsFleet"


def _commander_list(admirals: bool, offers: bool) -> str:
    return f"{PLAYER_MUT}.Access{'Admirals' if admirals else 'Generals'}{'Offer' if offers else ''}"


def _diff(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """a 里与 b 不同的项。"""
    return {k: v for k, v in a.items() if b.get(k) != v}


@dataclass
class ActionResult:
    ok: bool
    action: str
    detail: str = ""
    before: Any = None
    after: Any = None

    def __str__(self) -> str:
        mark = "✓" if self.ok else "✗"
        change = f"（{self.before} → {self.after}）" if self.before != self.after else ""
        return f"{mark} {self.action}{change} {self.detail}".rstrip()


class Actions:
    def __init__(self, bridge: Bridge) -> None:
        self.b = bridge

    # ------------------------------------------------------------ 通用
    def _why_not(self, cmd: str, path=None) -> str:
        try:
            return plain(self.b.read(f"[GetDesc({cmd})]", path))[:200]
        except GameError:
            return ""

    def _probe(self, expr: str, path=None) -> str | None:
        """读一个表达式；读不到（对象已不在列表里、函数在当前状态下求值失败）给 None。"""
        try:
            return plain(self.b.read(f"[{expr}]", path))
        except GameError:
            return None

    def _run(self, name: str, cmd: str, probe: Callable[[], Any], expect: Callable[[Any], bool] | None,
             path=None, wait: float = 1.5, stmt: str = "") -> ActionResult:
        """expect 为 None 时只要求前后读数不同（开关类命令没有固定的目标值）。
        stmt 给定时执行它而不是 Execute(cmd)（界面 onclick 不经 Execute 的，如外交行动），前置仍按 IsValid(cmd)。"""
        before = probe()
        if expect is not None and expect(before):
            return ActionResult(True, name, "已是目标状态", before, before)
        if self.b.read(f"[IsValid({cmd})]", path) != "1":
            return ActionResult(False, name, f"不可执行：{self._why_not(cmd, path) or '游戏判定不可用'}", before, before)
        self.b.exec(stmt or f"Execute({cmd})", path)
        done = expect or (lambda v: v != before)
        after = before
        t0 = time.time()
        while time.time() - t0 < wait:
            after = probe()
            if done(after):
                return ActionResult(True, name, "", before, after)
            time.sleep(0.1)
        return ActionResult(False, name, "已执行但没看到生效", before, after)

    def command(self, cmd: str, probe: str | Callable[[], Any], path=None, target: str | None = None,
                probe_path=None, name: str = "", wait: float = 1.5) -> ActionResult:
        """按清单执行任意一条游戏命令（docs/actions.md 的「命令」列，接收对象换成实际路径）。
        probe：执行前后各读一次的表达式（默认在 path 上求值，另给 probe_path 时在它上面求值）；
        target 给定时要求读到它，否则只要求读数变化。
        例：command("Building.ToggleSubsidies", "Building.IsSubsidized", path=建筑路径)。"""
        if isinstance(probe, str):
            expr, ppath = probe, path if probe_path is None else probe_path
            probe = lambda: self._probe(expr, ppath)   # noqa: E731
        expect = (lambda v: v == target) if target is not None else None
        return self._run(name or cmd, cmd, probe, expect, path=path, wait=wait)

    def _set_level(self, kind: str, level: str) -> ActionResult:
        """预算面板上的五档：当前档位的按钮是唯一不可用的那个（界面也按这个显示选中）。"""
        if level not in LEVELS:
            raise ValueError(f"档位只能取 {LEVELS}")

        def probe():
            vals = self.b.read_many([f"IsValid({PLAYER}.Set{kind}{t})" for t in LEVELS])
            invalid = [t for t, v in zip(LEVELS, vals) if v == "0"]
            return invalid[0] if len(invalid) == 1 else None

        return self._run(f"{LEVEL_NAMES[kind]} {level}", f"{PLAYER}.Set{kind}{level}", probe, lambda v: v == level)

    # ------------------------------------------------------------ 税率 / 工资 / 补给舰
    def set_tax(self, level: str) -> ActionResult:
        """level 取 VeryLow / Low / Medium / High / VeryHigh。"""
        return self._set_level("TaxLevel", level)

    def set_wage(self, which: str, level: str) -> ActionResult:
        """which：Government（政府工资）/ Military（军队工资）。"""
        if which not in ("Government", "Military"):
            raise ValueError("which 取 Government / Military")
        return self._set_level(f"{which}WageLevel", level)

    def set_supply_ships(self, level: str) -> ActionResult:
        return self._set_level("SupplyShipConstructionLevel", level)

    # ------------------------------------------------------------ 关税与补贴、消费税
    def set_trade_policy(self, goods: str, side: str, policy: str) -> ActionResult:
        """side：Import / Export；policy：TariffsNone / TariffsLow / TariffsHigh / TariffsMax /
        SubventionsLow / SubventionsHigh / SubventionsMax（同一商品同一方向只有一种）。"""
        if side not in ("Import", "Export") or policy not in TRADE_POLICIES:
            raise ValueError(f"side 取 Import / Export，policy 取 {TRADE_POLICIES}")
        g = f"GetGoods('{goods}').Self"

        def probe():
            vals = self.b.read_many([f"{PLAYER}.Has{side}{p}({g})" for p in TRADE_POLICIES])
            return next((p for p, v in zip(TRADE_POLICIES, vals) if v == "1"), None)

        return self._run(f"{goods} {side} {policy}", f"{PLAYER}.Set{side}{policy}({g})", probe,
                         lambda v: v == policy)

    def toggle_consumption_tax(self, goods: str, on: bool | None = None) -> ActionResult:
        """on=True/False 时只在不是目标状态时切换，并核实到目标状态；None 保持纯开关。"""
        g = f"GetGoods('{goods}')"
        target = None if on is None else ("1" if on else "0")
        label = "开征" if on else "退出" if on is False else "开关"
        return self.command(f"{g}.ToggleTaxation({PLAYER})", f"{g}.IsTaxed({PLAYER})",
                            target=target, name=f"消费税{label} {goods}")

    # ------------------------------------------------------------ 国家级命令
    def country_command(self, cmd: str) -> ActionResult:
        """不带参数的国家命令，见 COUNTRY_COMMANDS（动员 / 复员全部军队、暂停 / 恢复建造、宣布破产……）。"""
        if cmd not in COUNTRY_COMMANDS:
            raise ValueError(f"只支持 {list(COUNTRY_COMMANDS)}")
        return self.command(f"{PLAYER}.{cmd}", f"{PLAYER}.{COUNTRY_COMMANDS[cmd]}", name=cmd)

    # ------------------------------------------------------------ 公司
    def company(self, key: str, create: bool = True) -> ActionResult:
        """创建 / 解散公司（公司面板的「建立」/「解散」）。公司类型没有全局取法，按列表找：
        创建在可建立的公司类型里找，解散在已有公司里找（上下文是 Company，类型取 Company.GetCompanyType）。"""
        name = f"{'创建' if create else '解散'}公司 {key}"
        lst, key_expr = (COMPANY_TYPES, "CompanyType.GetKey") if create else (COMPANIES, "Company.GetCompanyType.GetKey")
        keys = [r[0] for r in self.b.rows(lst, [key_expr])]
        if key not in keys:
            return ActionResult(False, name, f"{'可建立' if create else '已有'}的公司里没有它：{keys}")
        t = "CompanyType.Self" if create else "Company.GetCompanyType.Self"
        cmd = f"{PLAYER}.{'CreateCompany' if create else 'RemoveCompany'}({t})"
        return self.command(cmd, f"{PLAYER}.GetNumCompanies", path=[(lst, keys.index(key))], probe_path=[],
                            name=name)

    def toggle_charter(self, company: str, charter: str) -> ActionResult:
        """公司面板上授予 / 撤销特许状（Company.ToggleCharter(CompanyCharterType.Self)）。
        company 是公司类型 key，charter 是特许状中文名（如「贸易权」）。"""
        name = f"{company} 特许状「{charter}」开关"
        keys = [r[0] for r in self.b.rows(COMPANIES, ["Company.GetCompanyType.GetKey"])]
        if company not in keys:
            return ActionResult(False, name, f"已有的公司：{keys}")
        cpath = [(COMPANIES, keys.index(company))]
        path, names = self._find(CHARTER_TYPES, "CompanyCharterType.GetNameNoFormatting", charter, path=cpath)
        if not path:
            return ActionResult(False, name, f"可选特许状：{names}")
        probe = lambda: self.b.read_many(CHARTER_PROBES, cpath)   # noqa: E731
        return self._run(name, "Company.ToggleCharter(CompanyCharterType.Self)", probe, None, path=path)

    def target_charter(self, company: str, charter: str, building: str = "", region: str = "") -> ActionResult:
        """要选目标的特许状：产业 / 垄断（按建筑类型，Company.ToggleBuildingCharter）、殖民（按地区，
        Company.ToggleRegionCharter）。charter 是特许状类型 key（industry_charter …），building / region 是
        building_* / STATE_* 键。已授予时再执行一次就是撤销（与右键菜单同一条命令）。"""
        name = f"{company} 特许状 {charter} → {building or region}"
        keys = [r[0] for r in self.b.rows(COMPANIES, ["Company.GetCompanyType.GetKey"])]
        if company not in keys:
            return ActionResult(False, name, f"已有的公司：{keys}")
        if bool(building) == bool(region):
            raise ValueError("building 与 region 给且只给一个")
        cpath = [(COMPANIES, keys.index(company))]
        t = f"GetCompanyCharterType('{charter}').Self"
        cmd = (f"Company.ToggleBuildingCharter({t},GetBuildingType('{building}').Self)" if building
               else f"Company.ToggleRegionCharter({t},GetStateRegion('{region}').Self)")
        probe = lambda: sorted(plain(r[0]) for r in self.b.rows(   # noqa: E731
            f"Company.GetActiveCharters({t})", ["CompanyCharter.GetNameNoFormatting"], path=cpath))
        return self._run(name, cmd, probe, None, path=cpath)

    # ------------------------------------------------------------ 外交
    def country_ref(self, country: str) -> str:
        """把国家（tag 如 FRA，或 STATE_* 地区键）变成路径上的一步「=表达式」：桥接层按值求出该国作为
        非 const 上下文（数据系统没有全部国家的列表，也没有按 tag 取国家的函数，经它拥有的地区取）。"""
        if country.startswith("STATE_"):
            return f"=GetStateRegion('{country}').GetLargestStateOwner"
        if not _TAG_REGION:
            keys = gamedata.state_regions()
            for i in range(0, len(keys), 80):
                part = keys[i:i + 80]
                for k, tag in zip(part, self.b.read_many([f"GetStateRegion('{k}').GetLargestStateOwner.GetTagName"
                                                          for k in part])):
                    if tag:
                        _TAG_REGION.setdefault(plain(tag), k)
        if country not in _TAG_REGION:
            raise ValueError(f"找不到拥有地区的国家 {country}")
        return f"=GetStateRegion('{_TAG_REGION[country]}').GetLargestStateOwner"

    def state_ref(self, region: str) -> list:
        """某地区里最大那个州的路径（别国的州也行）：GetStateRegion(..).GetLargestStateInRegion 要求非 const 的地区，
        建不起来；改为经地区的最大拥有国（「=表达式」）走它的 Country.AccessStates，按地区 id 找州。"""
        rid = self.b.read(f"[GetStateRegion('{region}').GetID]")
        owner = [(f"=GetStateRegion('{region}').GetLargestStateOwner", 0)]
        ids = [r[0] for r in self.b.rows("Country.AccessStates", ["State.GetStateRegion.GetID"], path=owner)]
        return owner + [("Country.AccessStates", ids.index(rid))] if rid in ids else []

    def diplomatic_actions(self, country: str) -> list[dict[str, Any]]:
        """对某国可用 / 可能的外交行动（国家面板「外交」下拉框里的那些）。"""
        ref = [(self.country_ref(country), 0)]
        out = []
        for lst in DIPLO_ACTION_LISTS:
            for key, name, valid, active, why in self.b.rows(
                    f"Country.{lst}", ["DiplomaticAction.GetType.GetKey",
                                       "DiplomaticAction.GetNameNoFormatting",
                                       "IsValid(DiplomaticAction.ExecuteAction)",
                                       "DiplomaticAction.IsActivePact",
                                       "GetDesc(DiplomaticAction.ExecuteAction)"],
                    path=ref):
                out.append({"action": key, "name": plain(name), "list": lst, "valid": valid == "1",
                            "active": active == "1", "why_not": plain(why)[:200]})
        return out

    def diplomatic_action(self, country: str, action: str) -> ActionResult:
        """对某国执行外交行动。action 是外交行动类型 key（increase_relations、embargo …）。
        界面按钮的 onclick 是 DiplomaticAction.ExecuteWithConfirmation：不需确认的直接发命令，需要确认的
        （宿敌、驱逐外交官……）弹出确认窗口 DiplomaticActionWindow，玩家点「确认」才发。这里一律走确认窗口那条：
        桥接层伪造窗口（字段从外交行动对象抄，见 _diplo_window），执行 DiplomaticActionWindow.ExecuteAction。
        **直接 Execute(DiplomaticAction.ExecuteAction) 游戏收下了却什么也不做**。要选州的外交行动不在这里。"""
        name = f"对 {country}：{action}"
        ref = [(self.country_ref(country), 0)]
        for lst in DIPLO_ACTION_LISTS:
            keys = [r[0] for r in self.b.rows(f"Country.{lst}", ["DiplomaticAction.GetType.GetKey"], path=ref)]
            if action in keys:
                path = ref + [(f"Country.{lst}", keys.index(action))]
                probe = lambda p=path: [plain(v or "") for v in self.b.read_many(DIPLO_PROBES, p)]   # noqa: E731
                before = probe()
                if self.b.read("[IsValid(DiplomaticAction.ExecuteAction)]", path) != "1":
                    return ActionResult(False, name, f"不可执行：{self._why_not('DiplomaticAction.ExecuteAction', path)}",
                                        before, before)
                self.b.exec_fake("Execute(DiplomaticActionWindow.ExecuteAction)", _diplo_window(len(path) - 1),
                                 path=path)
                return self._settle(name, probe, before)
        return ActionResult(False, name, "没有这个外交行动")

    def plays(self) -> list[dict[str, Any]]:
        """玩家参与的外交博弈。"""
        return [{"index": i, "name": plain(n), "initiator": plain(x), "target": plain(t)}
                for i, (n, x, t) in enumerate(self.b.rows(PLAYS, ["DiplomaticPlay.GetName",
                                                                    "DiplomaticPlay.GetInitiator.GetNameNoFormatting",
                                                                    "DiplomaticPlay.GetTarget.GetNameNoFormatting"]))]

    def start_play(self, play: str, country: str = "", state: str = "") -> ActionResult:
        """发起外交博弈（国家面板的博弈按钮；界面先弹确认窗口，确认发的就是这条命令）。
        play 是博弈类型 key（dp_humiliation、dp_make_protectorate、dp_conquer_state …）；
        目标是国家（country：tag）或州（state：STATE_* 地区键，取该地区最大的州）。"""
        t = f"GetDiplomaticPlayType('{play}')"
        if state:
            cmd = f"{t}.GetStartCommandState({PLAYER},State.Self)"
            ref = self.state_ref(state)
            if not ref:
                return ActionResult(False, f"发起 {play} → {state}", "找不到该地区的州")
        else:
            cmd = f"{t}.GetStartCommandCountry({PLAYER}.Self,Country.Self)"
            ref = [(self.country_ref(country), 0)]
        probe = lambda: [p["name"] for p in self.plays()]   # noqa: E731
        return self._run(f"发起 {play} → {country or state}", cmd, probe, None, path=ref)

    def war_goal(self, goal: int, cmd: str, play: int = -1, war: int = -1, side: str = "") -> ActionResult:
        """战争目标：cmd 取 MakeWarGoalPrimaryDemand（设为主要诉求，博弈阶段）/
        ToggleIsPressedInPotentialPeaceDeal（和谈时是否坚持，战争中）。目标在 plays() 的第 play 个博弈
        （side 取 Initiator / Target，默认 Initiator）或 wars() 的第 war 场战争（side 取 Attackers / Defenders）里。"""
        if cmd not in ("MakeWarGoalPrimaryDemand", "ToggleIsPressedInPotentialPeaceDeal"):
            raise ValueError("cmd 取 MakeWarGoalPrimaryDemand / ToggleIsPressedInPotentialPeaceDeal")
        if war >= 0:
            path = [(WARS, war), (f"War.Get{side or 'Attackers'}WarGoals", goal)]
        else:
            path = [(PLAYS, play), (f"DiplomaticPlay.Get{side or 'Initiator'}WarGoals", goal)]
        fields = ["WarGoal.GetName", f"WarGoal.IsPressedInPotentialPeaceDeal({PLAYER}.Self)", "WarGoal.IsPrimaryDemand"]
        probe = lambda: [plain(v or "") for v in self.b.read_many(fields, path)]   # noqa: E731
        return self._run(f"战争目标 {goal}（{'战争 ' + str(war) if war >= 0 else '博弈 ' + str(play)}）：{cmd}",
                         f"WarGoal.{cmd}({PLAYER}.Self)", probe, None, path=path)

    def wars(self) -> list[dict[str, Any]]:
        return [{"index": i, "name": plain(n), "peace_offered": p == "1"}
                for i, (n, p) in enumerate(self.b.rows(WARS, ["War.GetName", "War.HasActivePeaceDeal"]))]

    def peace(self, war: int, how: str) -> ActionResult:
        """战争面板上的和谈按钮：ProposePeaceDeal（按坚持的战争目标提和）/ SetWhitePeace（提白和）/
        Capitulate（投降，不可逆）。界面经 WarPanel.GetWar 取到战争，命令本身在 War 上，这里从玩家的战争列表走。"""
        if how not in ("ProposePeaceDeal", "SetWhitePeace", "Capitulate"):
            raise ValueError("how 取 ProposePeaceDeal / SetWhitePeace / Capitulate")
        path = [(WARS, war)]
        before_wars = [w["name"] for w in self.wars()]

        def probe():   # 对方接受或投降后战争结束、从列表消失；否则看和约状态
            names = [w["name"] for w in self.wars()]
            if names != before_wars:
                return {"wars": names}
            return dict(zip(PEACE_FIELDS, self.b.read_many(PEACE_FIELDS, path)))

        return self._run(f"战争 {war}：{how}", f"War.{how}({PLAYER}.Self)", probe, None, path=path)

    def accept_peace(self, war: int) -> ActionResult:
        """战争面板上「接受和约」的开关（War.ToggleAcceptPeace，要有正在谈的和约）。"""
        path = [(WARS, war)]
        probe = lambda: self.b.read_many([f"War.WouldAcceptActivePeaceDeal({PLAYER}.Self)", "War.HasActivePeaceDeal"],
                                         path)   # noqa: E731
        return self._run(f"战争 {war}：接受和约开关", f"War.ToggleAcceptPeace({PLAYER}.Self)", probe, None, path=path)

    def play_stance(self, play: int, cmd: str) -> ActionResult:
        """外交博弈中的表态：Yield（退让）/ DeclareNeutrality / BeOnTheFence / LeanTowardsInitiator /
        LeanTowardsTarget / SupportInitiator / SupportTarget / SwitchSide。"""
        if cmd not in PLAY_STANCES:
            raise ValueError(f"cmd 取 {PLAY_STANCES}")
        ppath = [(PLAYS, play)]
        before_plays = [p["name"] for p in self.plays()]

        def probe():   # 表态改变博弈里的阵营；退让 / 中立后玩家不再参与，博弈从列表里消失
            if [p["name"] for p in self.plays()] != before_plays:
                return {"plays": [p["name"] for p in self.plays()]}
            return dict(zip(PLAY_SIDES, self.b.read_many([f"DiplomaticPlay.{s}({PLAYER})" for s in PLAY_SIDES], ppath)))

        return self._run(f"博弈 {play}：{cmd}", f"DiplomaticPlay.{cmd}({PLAYER})", probe, None, path=ppath)

    def treaties(self) -> list[dict[str, Any]]:
        """生效中的条约。"""
        return [{"index": i, "name": plain(n), "first": plain(f), "second": plain(s)}
                for i, (n, f, s) in enumerate(self.b.rows(TREATIES, ["Treaty.GetNameNoFormatting",
                                                                      "Treaty.GetFirstCountry.GetNameNoFormatting",
                                                                      "Treaty.GetSecondCountry.GetNameNoFormatting"]))]

    def withdraw_treaty(self, index: int) -> ActionResult:
        """退出条约（条约面板的「退出」，Treaty.WithdrawFromTreaty）。index 是 treaties() 的序号。"""
        ts = self.treaties()
        if not 0 <= index < len(ts):
            return ActionResult(False, f"退出条约 {index}", f"只有 {len(ts)} 个条约")
        t = ts[index]
        probe = lambda: [(x["name"], x["first"], x["second"]) for x in self.treaties()]   # noqa: E731
        return self._run(f"退出条约「{t['name']}」（{t['first']}—{t['second']}）", "Treaty.WithdrawFromTreaty", probe,
                         None, path=[(TREATIES, index)])

    def proposals(self) -> list[dict[str, Any]]:
        """别国发给玩家、待回复的提议（屏幕顶端的提议图标）。列表挂在界面对象 TopFrontend 上：
        TopFrontend.AccessProposals 每次都先清空 +0x30 的数组、再从游戏状态里按本地玩家重建，
        所以伪造一个只有 +0x30 空数组的对象就能读（见 docs/bridge.md）。"""
        rows = self.b.rows_fake(PROPOSALS, PROPOSAL_FIELDS, TOP_FRONTEND)
        return [{"index": i, "name": plain(n), "actor": plain(a), "kind": _proposal_kind(flags)}
                for i, (n, a, *flags) in enumerate(rows)]

    def answer_proposal(self, index: int, accept: bool) -> ActionResult:
        """接受 / 拒绝提议：条约、外交行动、外交要求、外交博弈中的拉拢（与提议弹窗上的按钮同一条命令）。"""
        props = self.proposals()
        if not 0 <= index < len(props):
            return ActionResult(False, f"回复提议 {index}", f"只有 {len(props)} 个提议")
        p = props[index]
        if p["kind"] not in PROPOSAL_COMMANDS:
            return ActionResult(False, f"回复提议 {index}", f"认不出提议种类：{p}")
        cmd = PROPOSAL_COMMANDS[p["kind"]][0 if accept else 1]
        name = f"{'接受' if accept else '拒绝'}「{p['name']}」（{p['actor']}）"
        before = [q["name"] for q in props]
        if self.b.read_fake(f"[IsValid({cmd})]", TOP_FRONTEND, path=[(PROPOSALS, index)]) != "1":
            return ActionResult(False, name, "不可执行", before, before)
        self.b.exec_fake(f"Execute({cmd})", TOP_FRONTEND, path=[(PROPOSALS, index)])
        return self._settle(name, lambda: [q["name"] for q in self.proposals()], before)

    def _settle(self, name: str, probe: Callable[[], Any], before: Any, wait: float = 1.5) -> ActionResult:
        """命令已发出：轮询到读数变化为止。"""
        after = before
        t0 = time.time()
        while time.time() - t0 < wait:
            after = probe()
            if after != before:
                return ActionResult(True, name, "", before, after)
            time.sleep(0.1)
        return ActionResult(False, name, "已执行但没看到生效", before, after)

    # ------------------------------------------------------------ 人物：将领
    def commanders(self, admirals: bool = False, offers: bool = False) -> list[dict[str, Any]]:
        """将领（admirals=True 为海军将领）；offers=True 时是可招募的人选。"""
        lst = _commander_list(admirals, offers)
        return [{"index": i, "name": plain(n), "rank": plain(r), "order": plain(o)}
                for i, (n, r, o) in enumerate(self.b.rows(lst, ["Character.GetFullName", "Character.GetRankName",
                                                                 "Character.GetOrderType.GetName"]))]

    def formations(self, fleets: bool = False) -> list[str]:
        return [plain(r[0]) for r in self.b.rows(FLEETS if fleets else ARMIES, ["MilitaryFormation.GetNameNoFormatting"])]

    def recruit_commander(self, index: int, admiral: bool = False, formation: int = -1,
                          direct: bool = False) -> ActionResult:
        """招募将领（人选来自 commanders(offers=True)）。formation 给定时直接编入该编队
        （Character.GetRecruitCommand(MilitaryFormation.Self)），否则不编入（GetRecruitCommandNoFormation）；
        direct=True 走招募面板上不经 Execute 的写法 Character.RecruitCharacterNoFormation。"""
        offers = _commander_list(admiral, True)
        path = [(offers, index)]
        if formation >= 0:
            path.append((FLEETS if admiral else ARMIES, formation))
            cmd = "Character.GetRecruitCommand(MilitaryFormation.Self)"
        else:
            cmd = "Character.GetRecruitCommandNoFormation"
        probe = lambda: len(self.commanders(admiral))   # noqa: E731
        return self._run(f"招募{'海军' if admiral else ''}将领 {index}", cmd, probe, None, path=path,
                         stmt="Character.RecruitCharacterNoFormation" if direct else "")

    def commander_action(self, index: int, cmd: str, admiral: bool = False, target: int = -1) -> ActionResult:
        """将领命令：Promote（晋升）/ Unassign（解除编队）/ Assign（编入第 target 个编队）/
        Order（下达第 target 个命令，命令列表见 Character.AccessOrders）。"""
        lst = _commander_list(admiral, False)
        path = [(lst, index)]
        # 编入 / 解除看所属编队（编入后要赶路：IsTravellingToFormation）
        formation = ["Character.GetMilitaryFormation.GetNameNoFormatting", "Character.IsTravellingToFormation"]
        if cmd == "Promote":
            stmt, probe_exprs = "Character.GetPromoteCommand", ["Character.GetRankName"]
        elif cmd == "Unassign":
            stmt, probe_exprs = "Character.UnassignFromFormation", formation
        elif cmd == "Assign":
            path.append((FLEETS if admiral else ARMIES, target))
            stmt, probe_exprs = "Character.AssignToFormation(MilitaryFormation.Self)", formation
        elif cmd == "Order":
            path.append(("Character.AccessOrders", target))
            stmt, probe_exprs = ("Character.SelectOrder(CommanderOrderType.Self)",
                                 ["Character.GetOrderType.GetName", "Character.GetNextOrderType.GetName"])
        else:
            raise ValueError("cmd 取 Promote / Unassign / Assign / Order")
        who = plain(self.b.read("[Character.GetFullName]", path[:1]))
        name = f"将领 {who}：{cmd}{'' if target < 0 else ' ' + str(target)}"

        def probe():
            # 将领列表按军衔排序：晋升、编入之后同一下标可能换了人，每次按名字重新找
            names = [plain(r[0]) for r in self.b.rows(lst, ["Character.GetFullName"])]
            if who not in names:
                return None
            return [plain(v or "") for v in self.b.read_many(probe_exprs, [(lst, names.index(who))])]

        return self._run(name, stmt, probe, None, path=path)

    # ------------------------------------------------------------ 权力集团
    def bloc(self) -> dict[str, Any]:
        """玩家所在权力集团的成员与原则。"""
        if self._probe(f"{PLAYER}.IsInPowerBloc") != "1":
            return {"in_bloc": False}
        return {"in_bloc": True, "name": self._probe(f"{BLOC}.GetNameNoFormatting"),
                "members": [plain(r[0]) for r in self.b.rows(f"{BLOC}.GetMembers", ["Country.GetNameNoFormatting"])],
                "principles": [plain(r[0]) for r in self.b.rows(f"{BLOC}.GetPrinciples", ["PowerBlocPrinciple.GetName"])]}

    def kick_from_bloc(self, member: str) -> ActionResult:
        """把成员踢出权力集团（集团领袖，PowerBloc.Kick(Country.Self)）。member 是成员国中文名。"""
        path, names = self._find(f"{BLOC}.GetMembers", "Country.GetNameNoFormatting", member)
        if not path:
            return ActionResult(False, f"踢出 {member}", f"成员：{names}")
        probe = lambda: self.bloc().get("members")   # noqa: E731
        return self._run(f"把 {member} 踢出权力集团", f"{BLOC}.Kick(Country.Self)", probe, None, path=path)

    def upgrade_principle(self, index: int) -> ActionResult:
        """升级权力集团原则（花授权，PowerBlocPrinciple.UpgradeToNextLevel）。"""
        probe = lambda: self.bloc().get("principles")   # noqa: E731
        return self._run(f"升级集团原则 {index}", "PowerBlocPrinciple.UpgradeToNextLevel", probe, None,
                         path=[(f"{BLOC}.GetPrinciples", index)])

    def form_country(self, formation: str) -> ActionResult:
        """成立国家（建国面板，CountryFormation.FormCountry）。formation 是可成立国家的中文名。"""
        path, names = self._find(FORMABLE, "CountryFormation.GetName", formation)
        if not path:
            return ActionResult(False, f"成立「{formation}」", f"可成立的：{names}")
        probe = lambda: self.b.read_many([f"{PLAYER}.GetTagName", f"{PLAYER}.GetNameNoFormatting"])   # noqa: E731
        return self._run(f"成立「{formation}」", f"CountryFormation.FormCountry({PLAYER})", probe, None, path=path)

    def support_candidate(self, formation: str, candidate: int) -> ActionResult:
        """统一运动里支持某个候选国（CountryFormation.SupportCandidate）。candidate 是候选国列表的序号。"""
        path, names = self._find(FORMABLE, "CountryFormation.GetName", formation)
        if not path:
            return ActionResult(False, f"支持「{formation}」候选国", f"可成立的：{names}")
        cpath = path + [("CountryFormation.AccessFormationCandidates", candidate)]
        probe = lambda: self._probe(f"CountryFormation.GetSupportedCandidateCountry({PLAYER}).GetNameNoFormatting",
                                    path)   # noqa: E731
        return self._run(f"支持「{formation}」候选国 {candidate}", f"CountryFormation.SupportCandidate({PLAYER},Country.Self)",
                         probe, None, path=cpath)

    def default_construction_fleet(self, fleet: int = -1) -> ActionResult:
        """新造军舰默认编入的舰队（右键菜单）：fleet 是 formations(fleets=True) 的序号，-1 为清除。
        **要用非 const 的玩家国家（PLAYER_MUT）**：经只读路径执行，游戏收下了却不生效。"""
        probe = lambda: [r[0] for r in self.b.rows(FLEETS, ["MilitaryFormation.IsDefaultConstructionFleet"])]   # noqa: E731
        if fleet < 0:
            return self.command(f"{PLAYER_MUT}.ClearDefaultConstructionFleet", probe, name="清除默认造舰舰队")
        return self.command(f"{PLAYER_MUT}.SetDefaultConstructionFleet(MilitaryFormation.Self)", probe,
                            path=[(FLEETS, fleet)], name=f"默认造舰舰队 → {fleet}")

    # ------------------------------------------------------------ 谈判
    def negotiate(self, ig_index: int) -> ActionResult:
        """与利益集团谈判（ig_index 是 IGS 列表下标）。"""
        return self.command(f"{PLAYER_MUT}.StartNegotiationWith(InterestGroup.Self)", f"{PLAYER}.IsNegotiating",
                            path=[(IGS, ig_index)], probe_path=[], name=f"与利益集团 {ig_index} 谈判")

    # ------------------------------------------------------------ 事件
    def events(self) -> list[dict[str, Any]]:
        """玩家待处理的事件与可选项（与事件窗口里看到的一致：条件不满足的选项不列出）。
        option 是事件窗口里的序号，choose_event_option 用它。"""
        out = []
        for eid, key, title, days, mine in self.b.events(EVENT_FIELDS):
            if mine != "1" or int(eid) in _ANSWERED:
                continue
            opts = self.b.rows_fake(EVENT_OPTIONS, OPTION_FIELDS, _event_window(int(eid)))
            out.append({"id": int(eid), "key": key, "title": plain(title), "days_left": int(days or 0),
                        "options": [{"option": i, "text": plain(row[0]), "enabled": row[1] == "1",
                                     "default": row[2] == "1",
                                     "desc": plain(row[3]) if len(row) > 3 else ""}
                                    for i, row in enumerate(opts)]})
        return out

    def choose_event_option(self, event_id: int, option: int) -> ActionResult:
        """事件窗口点第 option 个选项（EventOption.Select，界面上没有 Execute 包装）。
        事件窗口从数据系统走不到，桥接层伪造窗口对象（+0x88 事件句柄、+0x110 选项数组），见 docs/bridge.md。
        游戏不拒绝对同一事件的重复回答（暂停时事件要到下一天才移出），所以这里记下已答的事件。"""
        name = f"事件 {event_id} 选第 {option} 项"
        if event_id in _ANSWERED:
            return ActionResult(False, name, f"这个事件已经选过第 {_ANSWERED[event_id]} 项")
        ev = next((e for e in self.events() if e["id"] == event_id), None)
        if ev is None:
            return ActionResult(False, name, "玩家没有这个待处理事件")
        if not 0 <= option < len(ev["options"]):
            return ActionResult(False, name, f"只有 {len(ev['options'])} 个可选项")
        if not ev["options"][option]["enabled"]:
            return ActionResult(False, name, "这个选项不可用")
        name = f"事件 {ev['key']}「{ev['title']}」选「{ev['options'][option]['text']}」"
        before = self._signature()
        self.b.exec_fake("EventOption.Select", _event_window(event_id), path=[(EVENT_OPTIONS, option)])
        _ANSWERED[event_id] = option
        after = before
        t0 = time.time()
        while time.time() - t0 < 1.5:
            after = self._signature()
            if after != before:
                return ActionResult(True, name, "", _diff(before, after), _diff(after, before))
            time.sleep(0.1)
        return ActionResult(True, name, "已选；这个选项没有可读的即时变化（效果可能在之后结算）", before, after)

    def _signature(self) -> dict[str, Any]:
        """事件选项效果的粗略读数：定时修正、国库、威望、合法性、在推行的法律。"""
        vals = self.b.read_many([f"{PLAYER}.{f}" for f in SIGNATURE_FIELDS])
        sig: dict[str, Any] = dict(zip(SIGNATURE_FIELDS, (plain(v) if v else v for v in vals)))
        sig["modifiers"] = sorted(plain(r[0]) for r in self.b.rows(f"{PLAYER_MUT}.GetTimedModifiers",
                                                                   ["TimedModifier.GetName"]))
        return sig

    # ------------------------------------------------------------ 日志：剧本按钮、决议
    def journal(self) -> dict[str, Any]:
        """进行中的日志条目：名字、进度条数值、剩余天数、按钮（只列界面可见的），以及决议。"""
        entries = []
        for i, row in enumerate(self.b.rows(JOURNAL, JOURNAL_FIELDS)):
            key, name, progress, has_bar, value, pct, total, timeout, progressing, can_complete, goal = \
                [plain(x or "") for x in row]
            buttons = self.b.rows(JE_BUTTONS, ["ScriptedButton.GetName", f"IsValid({BUTTON_CMD})"], path=[(JOURNAL, i)])
            bars = []
            try:
                for j, (bname, bmax) in enumerate(self.b.rows(
                        JE_BARS, ["ScriptedProgressBar.GetName", "ScriptedProgressBar.GetMaxValue"],
                        path=[(JOURNAL, i)])):
                    bpath = [(JOURNAL, i), (JE_BARS, j)]
                    try:
                        bval = plain(self.b.read("[JournalEntry.GetCurrentBarValue(ScriptedProgressBar.Self)]",
                                                 bpath) or "")
                    except GameError:
                        bval = ""
                    bars.append({"name": plain(bname), "value": bval, "max": plain(bmax)})
            except GameError:
                pass
            entries.append({"key": key, "name": name, "progress": progress,
                            "has_progress": has_bar == "1", "progress_value": value,
                            "progress_percent": pct, "goal_total": total, "timeout_days": timeout,
                            "progressing": progressing == "1", "can_complete": can_complete == "1",
                            "goal": goal, "bars": bars,
                            "buttons": [{"name": plain(n), "possible": v == "1"} for n, v in buttons]})
        decisions = [{"name": plain(n), "possible": v == "1"}
                     for n, v in self.b.rows(DECISIONS, ["Decision.GetName", f"IsValid({DECISION_CMD})"])]
        return {"journal_entries": entries, "decisions": decisions}

    def press_button(self, entry: str, button: str) -> ActionResult:
        """日志条目上的剧本按钮（ScriptedButton.ExecuteEffect）。entry 是条目 key，button 是按钮名字。"""
        name = f"{entry} 的按钮「{button}」"
        keys = [r[0] for r in self.b.rows(JOURNAL, ["JournalEntry.GetType.GetKey"])]
        if entry not in keys:
            return ActionResult(False, name, f"没有进行中的日志条目 {entry}：{keys}")
        jpath = [(JOURNAL, keys.index(entry))]
        names = [plain(r[0]) for r in self.b.rows(JE_BUTTONS, ["ScriptedButton.GetName"], path=jpath)]
        if button not in names:
            return ActionResult(False, name, f"这个条目没有可见的按钮「{button}」：{names}")

        def probe():   # 按钮的可见与否跟着效果变（如「禁止鸦片贸易」按下后换成「解禁」），再加国家签名
            return {"buttons": [plain(r[0]) for r in self.b.rows(JE_BUTTONS, ["ScriptedButton.GetName"], path=jpath)],
                    **self._signature()}

        return self._run(name, BUTTON_CMD, probe, None, path=jpath + [(JE_BUTTONS, names.index(button))])

    def take_decision(self, decision: str) -> ActionResult:
        """决议（Decision.TakeDecision）。decision 是决议名字（界面上的中文名）。"""
        names = [plain(r[0]) for r in self.b.rows(DECISIONS, ["Decision.GetName"])]
        if decision not in names:
            return ActionResult(False, f"决议「{decision}」", f"没有这个决议：{names}")
        return self._run(f"决议「{decision}」", DECISION_CMD, self._signature, None,
                         path=[(DECISIONS, names.index(decision))])

    # ------------------------------------------------------------ 政治：机构、运动、立法、修正案
    def _find(self, lst: str, name_expr: str, name: str, path=None) -> tuple[list, list[str]]:
        """在列表里按名字找一项，返回（路径或 []，全部名字）。"""
        names = [plain(r[0]) for r in self.b.rows(lst, [name_expr], path=path)]
        return ((path or []) + [(lst, names.index(name))] if name in names else []), names

    def set_institution(self, institution: str, level: int) -> ActionResult:
        """机构投入等级（政治面板「机构」页的等级按钮）。institution 是机构名字（如「教育」）。"""
        name = f"机构「{institution}」投入 → {level}"
        path, names = self._find(INSTITUTIONS, "Institution.GetNameNoFormatting", institution)
        if not path:
            return ActionResult(False, name, f"没有这个机构：{names}")
        levels = [r[0] for r in self.b.rows(INSTITUTION_LEVELS, ["InstitutionInvestmentLevel.GetLevel"], path=path)]
        if str(level) not in levels:
            return ActionResult(False, name, f"可选等级：{levels}")
        probe = lambda: self._probe("Institution.GetTargetInvestmentLevel", path)   # noqa: E731
        return self._run(name, "Institution.StartChangingLevelTo(InstitutionInvestmentLevel.GetLevel)", probe,
                         lambda v: v == str(level), path=path + [(INSTITUTION_LEVELS, levels.index(str(level)))])

    def stop_institution_change(self, institution: str) -> ActionResult:
        name = f"机构「{institution}」停止调整"
        path, names = self._find(INSTITUTIONS, "Institution.GetNameNoFormatting", institution)
        if not path:
            return ActionResult(False, name, f"没有这个机构：{names}")
        return self.command("Institution.StopSizeChange", "Institution.IsChangingLevel", path=path, target="0",
                            name=name)

    def toggle_movement(self, movement: str, action: str) -> ActionResult:
        """扶持 / 压制政治运动（再按一次取消）。action：Bolstering / Suppression。"""
        if action not in ("Bolstering", "Suppression"):
            raise ValueError("action 取 Bolstering / Suppression")
        name = f"{'扶持' if action == 'Bolstering' else '压制'}运动「{movement}」"
        path, names = self._find(MOVEMENTS, "PoliticalMovement.GetNameNoFormatting", movement)
        if not path:
            return ActionResult(False, name, f"没有这个运动：{names}")
        probe = "PoliticalMovement.IsBolstered" if action == "Bolstering" else "PoliticalMovement.IsSuppressed"
        return self.command(f"PoliticalMovement.Toggle{action}", probe, path=path, name=name)

    def movements(self) -> list[dict[str, Any]]:
        """进行中的政治运动：名称 / 扶持 / 压制 / 意识形态 / activism / 支持者人数。"""
        return [{"name": plain(n), "bolstered": b == "1", "suppressed": s == "1", "ideology": plain(i),
                 "radicalism": number(r) or 0.0, "supporters": number(p) or 0.0}
                for n, b, s, i, r, p in self.b.rows(
                    MOVEMENTS, ["PoliticalMovement.GetNameNoFormatting", "PoliticalMovement.IsBolstered",
                                "PoliticalMovement.IsSuppressed",
                                "PoliticalMovement.GetCoreIdeology.GetNameNoFormatting",
                                "PoliticalMovement.GetRadicalism|3",
                                "PoliticalMovement.GetNumSupportingIndividuals|0"])]

    def stop_enacting(self) -> ActionResult:
        """取消正在推行的法律（Law.StopEnacting，在该法律组的可选法律里）。"""
        from agent.observe import laws as current_laws
        for row in current_laws(self.b).values():
            alts = self.b.rows(LAW_ALTERNATIVES, ["Law.IsBeingEnacted", "Law.GetLawType.GetName"], path=row.path)
            for i, (enacting, law_name) in enumerate(alts):
                if enacting == "1":
                    return self.command("Law.StopEnacting", f"{PLAYER}.IsEnactingLaw",
                                        path=row.path + [(LAW_ALTERNATIVES, i)], probe_path=[], target="0",
                                        name=f"取消推行「{plain(law_name)}」")
        return ActionResult(False, "取消推行法律", "没有正在推行的法律")

    def impose_law(self, subject: str, law: str) -> ActionResult:
        """对附属国强加法律（右键菜单里的 Law.StartImposing）。subject、law 都是界面上的中文名。"""
        name = f"对「{subject}」强加「{law}」"
        spath, names = self._find(SUBJECTS, "Country.GetNameNoFormatting", subject)
        if not spath:
            return ActionResult(False, name, f"没有这个附属国：{names}")
        for lst in LAW_LISTS:
            for i in range(len(self.b.rows(f"Country.{lst}", ["Law.GetGroup.GetKey"], path=spath))):
                gpath = spath + [(f"Country.{lst}", i)]
                path, _ = self._find(LAW_ALTERNATIVES, "Law.GetLawType.GetName", law, path=gpath)
                if path:
                    # 附属国要到之后的结算才开始推行；即时可读的是强加冷却（12 个月内不能再强加），命令随之不可用
                    return self.command("Law.StartImposing", "IsValid(Law.StartImposing)", path=path, name=name)
        return ActionResult(False, name, "这个附属国没有可选的这条法律")

    def repeal_amendment(self, amendment: str) -> ActionResult:
        """废除修正案（Amendment.Repeal，挂在现行法律上）。"""
        from agent.observe import laws as current_laws
        name = f"废除修正案「{amendment}」"
        for row in current_laws(self.b).values():
            path, _ = self._find(AMENDMENTS, "Amendment.GetNameNoFormatting", amendment, path=row.path)
            if path:
                probe = lambda p=row.path: sorted(   # noqa: E731
                    plain(r[0]) for r in self.b.rows(AMENDMENTS, ["Amendment.GetNameNoFormatting"], path=p))
                return self._run(name, "Amendment.Repeal", probe, lambda v: amendment not in v, path=path)
        return ActionResult(False, name, "现行法律上没有这个修正案")

    # ------------------------------------------------------------ 经济：建造队列
    def construction_queue(self, private: bool = False) -> list[dict[str, Any]]:
        """政府（或私人）建造队列，按队列顺序。"""
        rows = self.b.rows(PRIVATE_QUEUE if private else GOV_QUEUE, QUEUE_FIELDS)
        return [{"index": i, "building": k, "state": plain(s), "weeks_left": w, "under_construction": u == "1"}
                for i, (k, s, w, u) in enumerate(rows)]

    def _queue_keys(self, lst: str) -> list[tuple[str, str]]:
        return [(r[0], plain(r[1])) for r in self.b.rows(lst, QUEUE_FIELDS[:2])]

    def move_construction(self, index: int, how: str, private: bool = False) -> ActionResult:
        """调整队列顺序：how 取 Up / Down / ToTop / ToBottom（队列面板上的箭头）。"""
        if how not in ("Up", "Down", "ToTop", "ToBottom"):
            raise ValueError("how 取 Up / Down / ToTop / ToBottom")
        lst = PRIVATE_QUEUE if private else GOV_QUEUE
        keys = self._queue_keys(lst)
        name = f"建造队列第 {index} 项 Move{how}"
        if not 0 <= index < len(keys):
            return ActionResult(False, name, f"队列只有 {len(keys)} 项")
        want = keys[:index] + keys[index + 1:]
        to = {"Up": max(index - 1, 0), "Down": min(index + 1, len(keys) - 1), "ToTop": 0, "ToBottom": len(keys) - 1}[how]
        want.insert(to, keys[index])
        name = f"{keys[index][0]} @ {keys[index][1]}：队列 {index} → {to}"
        return self._run(name, f"ConstructionQueueElement.Move{how}", lambda: self._queue_keys(lst),
                         lambda v: v == want, path=[(lst, index)])

    def cancel_construction(self, index: int, private: bool = False) -> ActionResult:
        lst = PRIVATE_QUEUE if private else GOV_QUEUE
        keys = self._queue_keys(lst)
        if not 0 <= index < len(keys):
            return ActionResult(False, f"取消建造队列第 {index} 项", f"队列只有 {len(keys)} 项")
        return self._run(f"取消建造 {keys[index][0]} @ {keys[index][1]}", "ConstructionQueueElement.CancelConstruction",
                         lambda: len(self._queue_keys(lst)), lambda v: v == len(keys) - 1, path=[(lst, index)])

    def construction_speed(self, pm: str = "", pause: bool | None = None) -> ActionResult:
        """建造面板顶上的全局命令：pm 给定时把全部建造部门换成该生产方式（ChangeAllConstructionSpeed），
        pause=True / False 时暂停 / 恢复全部建造部门（PauseAllConstruction / ResumeAllConstruction）。"""
        if pause is not None:
            cmd, other = ("PauseAllConstruction", "ResumeAllConstruction") if pause else \
                ("ResumeAllConstruction", "PauseAllConstruction")
            return self.command(cmd, f"IsValid({other})", target="1", name=cmd)
        keys = [r[0] for r in self.b.rows(CONSTRUCTION_SPEEDS, ["ProductionMethod.GetKey"])]
        if pm not in keys:
            return ActionResult(False, f"全部建造部门 → {pm}", f"可选：{keys}")
        cmd = "ChangeAllConstructionSpeed(ProductionMethod.Self)"
        # 全部换好后同一命令不可用（「该生产方式已在所有建筑中激活」）
        return self.command(cmd, f"IsValid({cmd})", path=[(CONSTRUCTION_SPEEDS, keys.index(pm))], target="0",
                            name=f"全部建造部门 → {pm}")

    # ------------------------------------------------------------ 经济：州（法令、并入、殖民）
    def _state_path(self, state: int | str) -> list:
        rows = self.b.rows(STATES, ["State.GetID", "State.GetNameNoFormatting"])
        si = next((i for i, (sid, n) in enumerate(rows) if str(state) in (sid, plain(n))), None)
        return [] if si is None else [(STATES, si)]

    def _decrees(self, spath) -> list[str]:
        return sorted(plain(r[0]) for r in self.b.rows("State.AccessDecrees", ["Decree.GetName"], path=spath))

    def set_decree(self, state: int | str, decree: str) -> ActionResult:
        """在州里颁布法令（DecreeType.GetSetCommand(State.Self)）。decree 是法令中文名。"""
        name = f"{state} 颁布法令「{decree}」"
        spath = self._state_path(state)
        if not spath:
            return ActionResult(False, name, f"玩家没有州 {state}")
        active = self._decrees(spath)
        if decree in active:                     # GetPotentialDecrees 不含已生效的，先查现有的
            return ActionResult(True, name, f"已是目标状态（现有：{active}）", active, active)
        path, names = self._find("State.GetPotentialDecrees", "DecreeType.GetNameNoFormatting", decree, path=spath)
        if not path:
            return ActionResult(False, name, f"可颁布的法令：{names}")
        return self._run(name, "DecreeType.GetSetCommand(State.Self)", lambda: self._decrees(spath),
                         lambda v: decree in v, path=path)

    def remove_decree(self, state: int | str, decree: str) -> ActionResult:
        name = f"{state} 撤销法令「{decree}」"
        spath = self._state_path(state)
        path, names = self._find("State.AccessDecrees", "Decree.GetName", decree, path=spath) if spath else ([], [])
        if not path:
            return ActionResult(False, name, f"该州现有法令：{names}")
        return self._run(name, "Decree.GetRemoveCommand", lambda: self._decrees(spath),
                         lambda v: decree not in v, path=path)

    def colonizing(self) -> list[str]:
        """正在殖民的州（殖民开始后的下一次结算就作为玩家的州出现，IsGrowingColony；IsBeingColonized 不是它）。"""
        return sorted(plain(n) for n, c in self.b.rows(STATES, ["State.GetNameNoFormatting", "State.IsGrowingColony"])
                      if c == "1")

    def colonize(self, region: str) -> ActionResult:
        """殖民一个地区（地图右键「殖民」：State.GetStateRegion.Colonize）。region 是 STATE_* 键，
        直接用全局 GetStateRegion 取到同一个 StateRegion。
        暂停时殖民地要到下一次结算才作为州出现，即时可读的是同一命令变为不可用（「我们在这里已经有殖民地」）。"""
        cmd = f"GetStateRegion('{region}').Colonize"
        return self.command(cmd, f"IsValid({cmd})", target="0", name=f"殖民 {region}")

    def state_action(self, state: int | str, cmd: str) -> ActionResult:
        """州上的命令：IncorporateState / UnincorporateState / TogglePauseColonization / AbandonColony。"""
        if cmd not in STATE_COMMANDS:
            raise ValueError(f"cmd 取 {list(STATE_COMMANDS)}")
        spath = self._state_path(state)
        if not spath:
            return ActionResult(False, f"{state}：{cmd}", f"玩家没有州 {state}")
        return self.command(f"State.{cmd}", lambda: self.b.read_many(STATE_COMMANDS[cmd], spath), path=spath,
                            name=f"{state}：{cmd}")

    # ------------------------------------------------------------ 经济：单个建筑
    def _building_path(self, state: int | str, building: str) -> tuple[list, str]:
        """state 是州 id 或州名；在该州已有建筑（State.AccessBuildings）里找 building。"""
        rows = self.b.rows(STATES, ["State.GetID", "State.GetNameNoFormatting"])
        si = next((i for i, (sid, n) in enumerate(rows) if str(state) in (sid, plain(n))), None)
        if si is None:
            return [], f"玩家没有州 {state}"
        keys = [r[0] for r in self.b.rows("State.AccessBuildings", ["Building.GetBuildingType.GetKey"],
                                          path=[(STATES, si)])]
        if building not in keys:
            return [], f"{plain(rows[si][1])} 没有 {building}"
        return [(STATES, si), ("State.AccessBuildings", keys.index(building))], ""

    def building_action(self, state: int | str, building: str, cmd: str, levels: int = 1) -> ActionResult:
        """建筑面板 / 右键菜单上的命令，见 BUILDING_COMMANDS（补贴、自动扩建、私有化、国有化、缩减、
        取消建造、暂停建造部门产出、生产方式恢复默认……）。Nationalize 时 levels 是国有化的级数。"""
        if cmd not in BUILDING_COMMANDS:
            raise ValueError(f"cmd 取 {list(BUILDING_COMMANDS)}")
        name = f"{building} @ {state}：{cmd}"
        path, why = self._building_path(state, building)
        if not path:
            return ActionResult(False, name, why)
        expr = BUILDING_COMMANDS[cmd]
        # GetBuildingType.* 是建筑类型上的命令（按类型生效），经建筑取到类型，与建筑浏览器里的同一条命令
        stmt = f"Building.NationalizeBuildingLevels('(int32){levels}')" if cmd == "Nationalize" else f"Building.{cmd}"

        def probe():
            # 州里的建筑按等级排序：缩减、取消建造之后同一下标可能换成别的建筑，每次按 key 重新找
            p, _ = self._building_path(state, building)
            if not p:
                return None
            return self._pms(p) if expr == "PMS" else self._probe(expr, p)

        return self._run(name, stmt, probe, None, path=path)

    def _pms(self, path) -> list[str]:
        return [r[0] for r in self.b.rows(PM_GROUPS, ["Building.AccessProductionMethod(ProductionMethodGroup.Self).GetKey"],
                                          path=path)]

    # ------------------------------------------------------------ 研究
    def research(self, tech: str) -> ActionResult:
        t = f"GetTechnology('{tech}')"

        def probe():
            vals = self.b.read_many([f"{t}.IsResearching({PLAYER}.Self)", f"{t}.HasResearchedTech({PLAYER}.Self)"])
            return "研究中" if vals[0] == "1" else "已完成" if vals[1] == "1" else "未研究"

        return self._run(f"研究 {tech}", f"{t}.Research({PLAYER}.Self)", probe, lambda s: s != "未研究")

    def research_queue(self) -> list[str]:
        """研究队列（正在研究的不在内），按顺序。科技没有 GetKey，按中文名对回游戏 id。"""
        by_name = _name_index("technologies")
        return [by_name.get(plain(r[0]), plain(r[0])) for lst in ("GetResearchQueueTop", "GetResearchQueueBottom")
                for r in self.b.rows(f"{PLAYER_MUT}.{lst}", ["Technology.GetNameNoFormatting"])]

    def queue_research(self, tech: str, how: str = "AddToQueueWithUnlocks") -> ActionResult:
        """科技树上的按钮：how 取 ResearchWithUnlocks（点击：连同前置一起，前置先研究）/
        AddToQueueWithUnlocks（Shift 点击：连同前置加进队尾）/ RemoveFromQueue（移出队列）。"""
        if how not in ("ResearchWithUnlocks", "AddToQueueWithUnlocks", "RemoveFromQueue"):
            raise ValueError("how 取 ResearchWithUnlocks / AddToQueueWithUnlocks / RemoveFromQueue")
        t = f"GetTechnology('{tech}')"

        def probe():
            return {"researching": self._probe(f"{PLAYER}.GetCurrentlyResearchedTechnology.GetNameNoFormatting"),
                    "queue": self.research_queue()}

        return self._run(f"{tech}：{how}", f"{t}.{how}({PLAYER}.Self)", probe, None)

    # ------------------------------------------------------------ 政府
    def reform_government(self, members: list[int]) -> ActionResult:
        """members：改组后全部在朝集团在 IGS 列表里的下标。桥接层构造政治面板上的拟议对象，
        再 Execute(ReformGovernment.Confirm)，与玩家点「确认」同一条命令（见 docs/bridge.md）。"""
        def probe():
            return sorted(ig.name for ig in interest_groups(self.b) if ig.in_gov)

        igs = interest_groups(self.b)
        want = sorted(igs[i].name for i in members if 0 <= i < len(igs))
        name = f"改组政府为 {'、'.join(want)}"
        before = probe()
        if before == want:
            return ActionResult(True, name, "已是目标状态", before, before)
        if len(want) != len(members):
            return ActionResult(False, name, "利益集团下标越界", before, before)
        self.b.reform_government(members)
        after = before
        t0 = time.time()
        while time.time() - t0 < 1.5:
            after = probe()
            if after == want:
                return ActionResult(True, name, "", before, after)
            time.sleep(0.1)
        return ActionResult(False, name, "已执行但没看到生效", before, after)

    # ------------------------------------------------------------ 法律
    def enact_law(self, law: str, snap: Snapshot) -> ActionResult:
        gd = gamedata.get()
        info = gd.laws.get(law)
        if not info:
            return ActionResult(False, f"推行 {law}", "没有这条法律")
        group = info["group"]
        current = snap.laws.get(group)
        if current is None:
            return ActionResult(False, f"推行 {law}", f"本国没有法律组 {group}")
        if current.key == law:
            return ActionResult(True, f"推行 {law}", "已是现行法律", law, law)
        names = {n for n in (info.get("name") or {}).values()}
        alts = self.b.rows(LAW_ALTERNATIVES, ["Law.GetLawType.GetName"], path=current.path)
        idx = next((i for i, (n,) in enumerate(alts) if plain(n) in names), None)
        if idx is None:
            return ActionResult(False, f"推行 {law}", f"{group} 的可选法律里没有它")
        path = current.path + [(LAW_ALTERNATIVES, idx)]

        def probe():
            try:
                n = plain(self.b.read(f"[{PLAYER}.GetLawBeingEnacted.GetLawType.GetName]"))
            except GameError:
                return None
            return law if n in names else n or None

        return self._run(f"推行 {law}", "Law.StartEnacting", probe, lambda s: s == law, path=path)

    # ------------------------------------------------------------ 建造
    def build(self, state_id: int, building: str, snap: Snapshot) -> ActionResult:
        s = snap.state(state_id)
        name = f"建造 {building} @ {s.name if s else state_id}"
        if not s or building not in s.buildings:
            return ActionResult(False, name, "这个州没有这种建筑的建造入口")
        row = s.buildings[building]
        key = self.b.read("[Building.GetBuildingType.GetKey]", row.path)
        if key != building:   # 列表在快照之后变了
            return ActionResult(False, name, f"路径已失效（现在指向 {key}），需要重新读局面")
        probe = lambda: int(float(self.b.read("[Building.GetExpansionLevelsInQueue]", row.path) or 0))
        before = probe()
        return self._run(name, "Building.QueueConstruction", probe, lambda q: q > before, path=row.path)

    # ------------------------------------------------------------ 生产方式
    def set_pm(self, state_id: int, building: str, pm: str, snap: Snapshot,
               acceptable: list[str] | None = None) -> ActionResult:
        """acceptable：现行方式在其中就不换（策略给出的「差不多一样好」的方式）。"""
        s = snap.state(state_id)
        name = f"生产方式 {building} → {pm} @ {s.name if s else state_id}"
        row = s.buildings.get(building) if s else None
        if not row or row.levels <= 0:
            return ActionResult(False, name, "这个州没有建成的该建筑")
        groups = self.b.rows(PM_GROUPS, ["ProductionMethodGroup.GetKey",
                                         "Building.AccessProductionMethod(ProductionMethodGroup.Self).GetKey"],
                             path=row.path)
        for g, (gkey, cur) in enumerate(groups):
            gpath = row.path + [(PM_GROUPS, g)]
            options = [r[0] for r in self.b.rows(PM_OPTIONS, ["ProductionMethod.GetKey"], path=gpath)]
            if pm not in options:
                continue
            if acceptable and cur in acceptable:
                return ActionResult(True, name, f"现行 {cur} 已可接受", cur, cur)
            ppath = gpath + [(PM_OPTIONS, options.index(pm))]
            probe = lambda: self.b.read("[Building.AccessProductionMethod(ProductionMethodGroup.Self).GetKey]", gpath)
            return self._run(name, "ProductionMethod.GetSwitch(Building.Self)", probe, lambda v: v == pm, path=ppath)
        return ActionResult(False, name, "该建筑没有这个生产方式")


def states_index(b: Bridge) -> dict[int, int]:
    """州 id → AccessStates 下标（动作只需要路径时用，不必读完整快照）。"""
    rows = b.rows(STATES, ["State.GetID"])
    return {int(r[0]): i for i, r in enumerate(rows)}
