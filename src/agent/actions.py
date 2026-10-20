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
from agent.bridge import IGS, PLAYER, PLAYER_MUT, Bridge, GameError, plain
from agent.observe import STATES, TAX_LEVELS, Snapshot, interest_groups

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
OPTION_FIELDS = ["EventOption.GetText", "EventOption.IsEnabled", "EventOption.IsDefaultOption"]
SIGNATURE_FIELDS = ["GetGoldReserves", "GetPrestige", "GetGovernmentLegitimacy", "GetLawBeingEnacted.GetLawType.GetKey",
                    "IsEnactingLaw", "IsNegotiating"]   # 谈判事件答完 IsNegotiating 立刻变 0
_ANSWERED: dict[int, int] = {}      # 本进程已回答的事件 id → 选项

JOURNAL = f"{PLAYER_MUT}.AccessActiveJournalEntries"
JE_BUTTONS = "JournalEntry.GetScriptedButtons"      # 只含可见的按钮
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
             path=None, wait: float = 1.5) -> ActionResult:
        """expect 为 None 时只要求前后读数不同（开关类命令没有固定的目标值）。"""
        before = probe()
        if expect is not None and expect(before):
            return ActionResult(True, name, "已是目标状态", before, before)
        if self.b.read(f"[IsValid({cmd})]", path) != "1":
            return ActionResult(False, name, f"不可执行：{self._why_not(cmd, path) or '游戏判定不可用'}", before, before)
        self.b.exec(f"Execute({cmd})", path)
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

    def toggle_consumption_tax(self, goods: str) -> ActionResult:
        g = f"GetGoods('{goods}')"
        return self.command(f"{g}.ToggleTaxation({PLAYER})", f"{g}.IsTaxed({PLAYER})", name=f"消费税开关 {goods}")

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
                        "options": [{"option": i, "text": plain(t), "enabled": e == "1", "default": d == "1"}
                                    for i, (t, e, d) in enumerate(opts)]})
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
        """进行中的日志条目及其按钮（只列可见的，与界面一致），以及决议。"""
        entries = []
        for i, (key, name) in enumerate(self.b.rows(JOURNAL, ["JournalEntry.GetType.GetKey", "JournalEntry.GetName"])):
            buttons = self.b.rows(JE_BUTTONS, ["ScriptedButton.GetName", f"IsValid({BUTTON_CMD})"], path=[(JOURNAL, i)])
            entries.append({"key": key, "name": plain(name),
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
