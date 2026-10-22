"""玩家操作覆盖层：docs/actions.md 里剩余的玩家命令。

`Actions` 放的是常用的、已经反复验证的动作；这里把清单里其余接收对象
（军事编队、舰船、舰船模板、造船队列、选中编队、指挥部、前线、入侵、海峡……）
逐个接到游戏数据系统的实际路径上。所有命令仍走界面按钮背后的同一条 `Execute`，
执行前后各读一次核实，不做直接改状态。

用法（MCP 的 act 会转到这里的同名方法）：

    a = Coverage(bridge)
    a.formations()                 # 玩家陆军编队
    a.formation_action(0, "Mobilize")
    a.select_formations([0, 1])    # 选中两个编队
    a.selected_action("MobilizeSelectedArmies")
"""

from __future__ import annotations

import ctypes
import time
from typing import Any

from agent.actions import ARMIES, FLEETS, PLAYS, ActionResult, Actions
from agent.bridge import GameError, PLAYER, PLAYER_MUT, plain

SHIP_LIST = f"{PLAYER_MUT}.GetShipList"
# 舰船选择只在造船/编队面板的编辑模式里存在；.Self 是让数据系统把它当成非 const 上下文
SHIP_SELECTION = "=AccessPlayer.GetShipList.GetActiveSelection.Self"

FORMATION_FIELDS = [
    "MilitaryFormation.GetNameNoFormatting",
    "MilitaryFormation.GetCountry.GetTagName",
    "MilitaryFormation.IsMobilized",
    "MilitaryFormation.IsSelected",
    "MilitaryFormation.GetNumShips",
    "MilitaryFormation.GetCurrentHQ.GetName",
]
SHIP_FIELDS = [
    "Ship.GetNameNoFormatting",
    "Ship.GetType.GetNameNoFormatting",
    "Ship.IsFlagship",
    "Ship.GetTemplate.GetNameNoFormatting",
    "Ship.IsToRetrofit",
    "Ship.GetFleet.GetNameNoFormatting",
    "Ship.GetGroup.GetKey",
]
TEMPLATE_FIELDS = [
    "ShipTemplate.GetNameNoFormatting",
    "ShipTemplate.GetType.GetNameNoFormatting",
    "ShipTemplate.IsBase",
    "ShipTemplate.IsCustom",
]
SHIP_CONSTRUCTION_FIELDS = [
    "ShipConstruction.GetShipTemplate.GetNameNoFormatting",
    "ShipConstruction.GetFleet.GetNameNoFormatting",
    "ShipConstruction.GetPlaceInQueue",
    "ShipConstruction.GetWeeksLeft",
    "ShipConstruction.IsInProgress",
]

# 编队命令 → (语句, 核实读数)。语句里的 .Self 参数由 path 上的对象提供。
FORMATION_COMMANDS: dict[str, tuple[str, list[str]]] = {
    "Mobilize": ("MilitaryFormation.Mobilize",
                 ["MilitaryFormation.IsMobilized", "MilitaryFormation.IsMobilizing"]),
    "Demobilize": ("MilitaryFormation.Demobilize",
                   ["MilitaryFormation.IsMobilized", "MilitaryFormation.IsMobilizing"]),
    "RaiseConscripts": ("MilitaryFormation.RaiseConscripts",
                        ["MilitaryFormation.GetNumConscripts",
                         "MilitaryFormation.GetConscriptsMobilizationPercentage"]),
    "Disband": ("MilitaryFormation.Disband", []),
    "DisembarkFormation": ("MilitaryFormation.DisembarkFormation",
                           ["MilitaryFormation.IsMobilized"]),
    "RecallForRepairs": ("MilitaryFormation.RecallForRepairs",
                         ["MilitaryFormation.GetNavalMission.GetType.GetNameNoFormatting"]),
    "RemoveNavalMission": ("MilitaryFormation.RemoveNavalMission",
                           ["MilitaryFormation.HasNavalMission",
                            "MilitaryFormation.GetNavalMission.GetType.GetNameNoFormatting"]),
    "RetrofitShips": ("MilitaryFormation.RetrofitShips",
                      ["MilitaryFormation.GetShipList.IsToRetrofit",
                       "MilitaryFormation.GetShipList.GetNumShipsToRetrofit"]),
    "RetrofitShipsAndStation": ("MilitaryFormation.RetrofitShipsAndStation",
                                ["MilitaryFormation.GetShipList.IsToRetrofit",
                                 "MilitaryFormation.GetShipList.GetNumShipsToRetrofit"]),
    "CancelRetrofitShips": ("MilitaryFormation.CancelRetrofitShips",
                            ["MilitaryFormation.GetShipList.IsToRetrofit",
                             "MilitaryFormation.GetShipList.GetNumShipsToRetrofit"]),
    "GetUpgradeAllUnitsCommand": ("MilitaryFormation.GetUpgradeAllUnitsCommand",
                                  ["MilitaryFormation.CanAnyUnitBeUpgraded"]),
}
SUPPLY_PRIORITIES = ("low", "medium", "high")


def _flags(vals: list[str | None]) -> list[str]:
    return [plain(v) if v is not None else "" for v in vals]


class Coverage(Actions):
    # ------------------------------------------------------------ 编队
    def formations(self, fleets: bool = False) -> list[dict[str, Any]]:
        """玩家陆军（fleets=False）或海军（fleets=True）编队。"""
        lst = FLEETS if fleets else ARMIES
        return [{"index": i, "name": plain(n), "tag": plain(t), "mobilized": m == "1",
                 "selected": s == "1", "ships": int(float(sh or 0)), "hq": plain(hq or "")}
                for i, (n, t, m, s, sh, hq) in enumerate(self.b.rows(lst, FORMATION_FIELDS))]

    def _formation_path(self, index: int, fleets: bool = False) -> list:
        return [(FLEETS if fleets else ARMIES, index)]

    def formation_action(self, index: int, cmd: str, fleets: bool = False) -> ActionResult:
        """编队上的无参数命令：Mobilize / Demobilize / RaiseConscripts / Disband /
        DisembarkFormation / RecallForRepairs / RemoveNavalMission / RetrofitShips /
        RetrofitShipsAndStation / CancelRetrofitShips / GetUpgradeAllUnitsCommand。"""
        if cmd not in FORMATION_COMMANDS:
            raise ValueError(f"cmd 取 {list(FORMATION_COMMANDS)}")
        path = self._formation_path(index, fleets)
        name = f"{plain(self._probe('MilitaryFormation.GetNameNoFormatting', path) or index)}：{cmd}"
        stmt, exprs = FORMATION_COMMANDS[cmd]
        if cmd == "Disband":
            before = [f["name"] for f in self.formations(fleets)]
            return self._run(name, stmt, lambda: [f["name"] for f in self.formations(fleets)],
                             lambda v: v != before, path=path)
        return self._run(name, stmt, lambda: _flags(self.b.read_many(exprs, path)), None, path=path)

    def select_supply_priority(self, index: int, priority: str, fleets: bool = False) -> ActionResult:
        """编队的补给优先级：low / medium / high（MilitaryFormation.SelectSupplyPriority）。"""
        if priority not in SUPPLY_PRIORITIES:
            raise ValueError(f"priority 取 {SUPPLY_PRIORITIES}")
        path = self._formation_path(index, fleets)
        probe = lambda: _flags(self.b.read_many(   # noqa: E731
            [f"MilitaryFormation.IsSupplyPrioritySelected('{p}')" for p in SUPPLY_PRIORITIES], path))
        i = SUPPLY_PRIORITIES.index(priority)
        return self._run(f"编队 {index} 补给优先级 → {priority}",
                         f"MilitaryFormation.SelectSupplyPriority('{priority}')", probe,
                         lambda v: v[i] == "1", path=path)

    def unit_entries(self, index: int, fleets: bool = False) -> list[dict[str, Any]]:
        """编队里的战斗单位条目（按单位类型分组）：当前 / 期望数量、是否默认类型。"""
        path = self._formation_path(index, fleets)
        return [{"index": i, "type": plain(t), "current": int(float(c or 0)),
                 "expected": int(float(e or 0)), "default": d == "1"}
                for i, (t, c, e, d) in enumerate(self.b.rows("MilitaryFormation.GetCombatUnitEntries",
                                                             ["MilitaryFormationUnitEntry.GetUnitType.GetNameNoFormatting",
                                                              "MilitaryFormationUnitEntry.GetCurrentNumTotalUnits",
                                                              "MilitaryFormationUnitEntry.GetExpectedNumTotalUnits",
                                                              "MilitaryFormationUnitEntry.IsDefaultType"], path=path))]

    def _unit_entry_path(self, index: int, entry: int, fleets: bool = False) -> list:
        return self._formation_path(index, fleets) + [("MilitaryFormation.GetCombatUnitEntries", entry)]

    def unit_entry_action(self, index: int, entry: int, cmd: str, fleets: bool = False) -> ActionResult:
        """按单位类型操作：SetDefaultUnitType / DisbandRegular / DisbandConscript /
        UpgradeRegular / UpgradeConscript（命令的接收对象是编队，参数是该条目的单位类型）。"""
        path = self._unit_entry_path(index, entry, fleets)
        name = f"{plain(self._probe('MilitaryFormationUnitEntry.GetUnitType.GetNameNoFormatting', path) or entry)}：{cmd}"
        current = lambda: [self._probe("MilitaryFormationUnitEntry.GetCurrentNumTotalUnits", path)]   # noqa: E731
        stmts = {
            "SetDefaultUnitType": "MilitaryFormation.GetSetDefaultUnitTypeCommand(MilitaryFormationUnitEntry.GetUnitType.Self)",
            "DisbandRegular": "MilitaryFormation.GetDisbandUnitTypeRegularCommand(MilitaryFormationUnitEntry.GetUnitType.Self)",
            "DisbandConscript": "MilitaryFormation.GetDisbandUnitTypeConscriptCommand(MilitaryFormationUnitEntry.GetUnitType.Self)",
            "UpgradeRegular": "MilitaryFormation.GetUpgradeRegularUnitTypeCommand(MilitaryFormationUnitEntry.GetUnitType.Self)",
            "UpgradeConscript": "MilitaryFormation.GetUpgradeConscriptUnitTypeCommand(MilitaryFormationUnitEntry.GetUnitType.Self)",
        }
        if cmd not in stmts:
            raise ValueError(f"cmd 取 {list(stmts)}")
        if cmd == "SetDefaultUnitType":
            return self._run(name, stmts[cmd],
                             lambda: [self._probe("MilitaryFormationUnitEntry.IsDefaultType", path)], None,
                             path=path)
        return self._run(name, stmts[cmd], current, None, path=path)

    def unit_group_action(self, index: int, group: int, cmd: str = "UpgradeGroup",
                          fleets: bool = False) -> ActionResult:
        """按单位组操作：UpgradeGroup（MilitaryFormation.GetUpgradeUnitGroupCommand(CombatUnitGroup.Self)）。"""
        path = self._formation_path(index, fleets) + [("MilitaryFormation.GetEligibleGroups", group)]
        name = f"{plain(self._probe('CombatUnitGroup.GetName', path) or group)}：{cmd}"
        if cmd != "UpgradeGroup":
            raise ValueError("cmd 取 UpgradeGroup")
        return self._run(name, "MilitaryFormation.GetUpgradeUnitGroupCommand(CombatUnitGroup.Self)",
                         lambda: [self._probe("MilitaryFormation.GetNumRegulars",
                                              self._formation_path(index, fleets))], None, path=path)

    def combat_units(self, index: int, entry: int, fleets: bool = False) -> list[dict[str, Any]]:
        """某个单位类型条目下的具体战斗单位。"""
        path = self._unit_entry_path(index, entry, fleets)
        return [{"index": i, "name": plain(n), "type": plain(t), "conscript": c == "1",
                 "manpower": int(float(m or 0))}
                for i, (n, t, c, m) in enumerate(self.b.rows("MilitaryFormationUnitEntry.GetCombatUnits",
                                                             ["CombatUnit.GetName", "CombatUnit.GetType",
                                                              "CombatUnit.IsConscript", "CombatUnit.GetManpowerRaw"],
                                                             path=path))]

    def combat_unit_action(self, index: int, entry: int, unit: int, cmd: str = "Disband",
                           fleets: bool = False) -> ActionResult:
        """单个战斗单位：Disband（CombatUnit.GetMilitaryFormation.GetDisbandUnitCommand(CombatUnit.Self)）。"""
        path = self._unit_entry_path(index, entry, fleets) + [("MilitaryFormationUnitEntry.GetCombatUnits", unit)]
        name = f"{plain(self._probe('CombatUnit.GetName', path) or unit)}：{cmd}"
        if cmd != "Disband":
            raise ValueError("cmd 取 Disband")
        before = len(self.combat_units(index, entry, fleets))
        return self._run(name, "CombatUnit.GetMilitaryFormation.GetDisbandUnitCommand(CombatUnit.Self)",
                         lambda: len(self.combat_units(index, entry, fleets)),
                         lambda v: v == before - 1, path=path)

    def mobilization_options(self, index: int, fleets: bool = False) -> list[dict[str, Any]]:
        """编队的动员选项（MobilizationOption）及启用状态。"""
        path = self._formation_path(index, fleets)
        return [{"index": i, "name": plain(n), "active": a == "1", "possible": p == "1"}
                for i, (n, a, p) in enumerate(self.b.rows(
                    "MilitaryFormation.GetMobilizationOptions",
                    ["MobilizationOption.GetNameNoFormatting",
                     "MobilizationOption.IsActivated(MilitaryFormation.Self)",
                     "MobilizationOption.IsPossible(MilitaryFormation.Self)"], path=path))]

    def mobilization_action(self, index: int, option: int, fleets: bool = False) -> ActionResult:
        """开关一个动员选项：MobilizationOption.Toggle(MilitaryFormation.Self)。"""
        path = self._formation_path(index, fleets) + [("MilitaryFormation.GetMobilizationOptions", option)]
        name = f"动员选项 {option} 开关"
        return self._run(name, "MobilizationOption.Toggle(MilitaryFormation.AccessSelf)",
                         lambda: [self._probe("MobilizationOption.IsActivated(MilitaryFormation.AccessSelf)", path)],
                         None, path=path, wait=3.0)

    def naval_missions(self, index: int, fleets: bool = True) -> list[dict[str, Any]]:
        """舰队可执行的海军任务类型（MilitaryFormation.GetPotentialMissionsTypes）。"""
        path = self._formation_path(index, fleets)
        return [{"index": i, "name": plain(n)}
                for i, (n,) in enumerate(self.b.rows("MilitaryFormation.GetPotentialMissionsTypes",
                                                     ["NavalMissionType.GetNameNoFormatting"], path=path))]

    def naval_mission_action(self, index: int, mission: int, cmd: str = "CreateNavalMission",
                             fleets: bool = True) -> ActionResult:
        """海军任务：CreateNavalMission / CreateNavalMissionWithPreviousArea（参数是任务类型列表项）。
        任务区域要在任务开始后用地图/任务面板编辑，本方法只建任务。"""
        if cmd not in ("CreateNavalMission", "CreateNavalMissionWithPreviousArea"):
            raise ValueError("cmd 取 CreateNavalMission / CreateNavalMissionWithPreviousArea")
        path = self._formation_path(index, fleets) + [("MilitaryFormation.GetPotentialMissionsTypes", mission)]
        name = f"舰队 {index}：{cmd} {mission}"
        return self._run(name, f"MilitaryFormation.{cmd}(NavalMissionType.AccessSelf)",
                         lambda: [self._probe("MilitaryFormation.HasNavalMission",
                                              self._formation_path(index, fleets)),
                                  self._probe("MilitaryFormation.GetNavalMission.GetType.GetNameNoFormatting",
                                              self._formation_path(index, fleets))], None, path=path)

    def upgrade_all(self, index: int, fleets: bool = False) -> ActionResult:
        """升级编队里全部可升级单位（MilitaryFormation.GetUpgradeAllUnitsCommand）。"""
        path = self._formation_path(index, fleets)
        name = f"编队 {index}：升级全部单位"
        return self._run(name, "MilitaryFormation.GetUpgradeAllUnitsCommand",
                         lambda: [self._probe("MilitaryFormation.CanAnyUnitBeUpgraded", path)], None, path=path)

    def select_formation(self, index: int, fleets: bool = False) -> ActionResult:
        """选中一个编队（界面里 shift-click 的 MilitaryFormation.Select）。"""
        path = self._formation_path(index, fleets)
        before = self.selected_formations()
        name = f"选中编队 {plain(self._probe('MilitaryFormation.GetNameNoFormatting', path) or index)}"
        self.b.exec("MilitaryFormation.Select", path=path)
        after = before
        for _ in range(15):
            after = self.selected_formations()
            if after != before:
                return ActionResult(True, name, "", before, after)
            time.sleep(0.1)
        return ActionResult(False, name, "选中名单没有变化", before, after)

    def selected_formations(self) -> list[str]:
        """当前选中的编队（界面上的选择列表，GetSelectedFormationsList）。"""
        try:
            raw = plain(self.b.read("[GetSelectedFormationsList]"))
        except GameError:
            return []
        return [x.strip() for x in raw.replace("，", ",").split(",") if x.strip()]

    def clear_selection(self) -> ActionResult:
        """清空编队选择：对每个选中的编队发 Deselect。"""
        before = self.selected_formations()
        if not before:
            return ActionResult(True, "清空编队选择", "本来就没有选中")
        for fleets in (False, True):
            lst = FLEETS if fleets else ARMIES
            for i, f in enumerate(self.formations(fleets)):
                if f["selected"]:
                    self.b.exec("MilitaryFormation.Deselect", path=[(lst, i)])
        after = self.selected_formations()
        return ActionResult(after == [], "清空编队选择", "", before, after)

    def selected_action(self, cmd: str, **kw: Any) -> ActionResult:
        """对「当前选中的编队」执行的全局命令（military_formation_panel.gui 右键菜单）：
        MobilizeSelectedArmies / DemobilizeSelectedArmies / RaiseConscriptsInSelectedArmies /
        MergeSelectedFormations / RetrofitShips / RetrofitShipsAndStation / CancelRetrofitShips /
        SetStrategicObjectiveForSelectedFormations(state_path=州路径) 等。"""
        if not self.selected_formations() and not any(
                f["selected"] for f in self.formations() + self.formations(True)):
            return ActionResult(False, cmd, "没有选中的编队")
        path = None
        stmt = cmd
        if cmd == "SetStrategicObjectiveForSelectedFormations":
            stmt = "SetStrategicObjectiveForSelectedFormations(State.Self)"
            path = kw.get("state_path")
        elif cmd in ("CreateNavalMissionsForSelectedFleets", "RemoveNavalMissionForSelectedFleets"):
            stmt = f"{cmd}(NavalMissionType.AccessSelf)"
            path = kw.get("mission_path")
        elif cmd == "SetCharacterOrderForSelectedFormations":
            stmt = "SetCharacterOrderForSelectedFormations(CommanderOrderType.Self)"
            path = kw.get("order_path")
        probes = ["GetSelectedFormationsList"]
        return self._run(cmd, stmt, lambda: _flags(self.b.read_many(probes)), None, path=path)

    # ------------------------------------------------------------ 舰船
    def _ship_list_path(self, fleet: int = -1, fleets: bool = False) -> list | None:
        return [(FLEETS if fleets else ARMIES, fleet)] if fleet >= 0 else None

    def ships(self, fleet: int = -1, fleets: bool = False) -> list[dict[str, Any]]:
        """玩家全部舰船，或某个编队（fleet 序号）里的舰船。"""
        path = self._ship_list_path(fleet, fleets)
        lst = ("MilitaryFormation.GetShipList.GetShips" if path else f"{SHIP_LIST}.GetShips")
        return [{"index": i, "name": plain(n), "type": plain(t), "flagship": f == "1",
                 "template": plain(tpl), "to_retrofit": r == "1", "fleet": plain(fl or ""),
                 "group": plain(g or "")}
                for i, (n, t, f, tpl, r, fl, g) in enumerate(self.b.rows(lst, SHIP_FIELDS, path=path))]

    def _ship_path(self, index: int, fleet: int = -1, fleets: bool = False) -> list:
        base = self._ship_list_path(fleet, fleets)
        return (base or []) + [("MilitaryFormation.GetShipList.GetShips" if base
                                else f"{SHIP_LIST}.GetShips", index)]

    def ship_action(self, index: int, cmd: str, fleet: int = -1, fleets: bool = False,
                    template: int = -1) -> ActionResult:
        """舰船命令：AssignAsFlagship / UnassignAsFlagship / CancelRetrofit / Retrofit /
        Decommission / SetNextFlagshipOrnament / SetPrevFlagshipOrnament /
        ToggleFlagshipSignalFlags / ChangeTemplate（template=模板序号）。"""
        path = self._ship_path(index, fleet, fleets)
        name = f"{plain(self._probe('Ship.GetNameNoFormatting', path) or index)}：{cmd}"
        probes = {
            "AssignAsFlagship": ["Ship.IsFlagship"],
            "UnassignAsFlagship": ["Ship.IsFlagship"],
            "CancelRetrofit": ["Ship.IsToRetrofit"],
            "Retrofit": ["Ship.IsToRetrofit"],
            "Decommission": [],
            "SetNextFlagshipOrnament": ["Ship.GetFlagshipOrnamentName"],
            "SetPrevFlagshipOrnament": ["Ship.GetFlagshipOrnamentName"],
            "ToggleFlagshipSignalFlags": ["Ship.HasFlagshipSignalFlags"],
            "ChangeTemplate": ["Ship.GetTemplate.GetNameNoFormatting"],
        }
        if cmd not in probes:
            raise ValueError(f"cmd 取 {list(probes)}")
        if cmd == "Decommission":
            before = [s["name"] for s in self.ships(fleet, fleets)]
            return self._run(name, "Ship.Decommission",
                             lambda: [s["name"] for s in self.ships(fleet, fleets)],
                             lambda v: v != before, path=path)
        if cmd == "ChangeTemplate":
            if template < 0:
                raise ValueError("ChangeTemplate 需要 template")
            path = path + self._template_path(template)
            return self._run(name, "Ship.ChangeTemplate(ShipTemplate.Self)",
                             lambda: _flags(self.b.read_many(probes[cmd],
                                                             self._ship_path(index, fleet, fleets))),
                             None, path=path)
        return self._run(name, f"Ship.{cmd}",
                         lambda: _flags(self.b.read_many(probes[cmd], path)), None, path=path)

    # ------------------------------------------------------------ 舰船模板
    def templates(self) -> list[dict[str, Any]]:
        """玩家可用的舰船模板（ShipList.GetShipTemplates）。"""
        return [{"index": i, "name": plain(n), "type": plain(t), "base": b == "1", "custom": c == "1"}
                for i, (n, t, b, c) in enumerate(self.b.rows(f"{SHIP_LIST}.GetShipTemplates",
                                                             TEMPLATE_FIELDS))]

    def _template_path(self, index: int) -> list:
        return [(f"{SHIP_LIST}.GetShipTemplates", index)]

    def template_action(self, index: int, cmd: str, fleet: int = -1, fleets: bool = False) -> ActionResult:
        """舰船模板命令：QueueConstruction / CancelConstruction / DeleteTemplate /
        SetAsDefaultForCountry / QueueConstructionForFleet(fleet) /
        CancelConstructionForFleet(fleet) / SetAsDefaultForFleet(fleet)。"""
        path = self._template_path(index)
        name = f"{plain(self._probe('ShipTemplate.GetNameNoFormatting', path) or index)}：{cmd}"
        if cmd in ("QueueConstructionForFleet", "CancelConstructionForFleet", "SetAsDefaultForFleet"):
            if fleet < 0:
                raise ValueError(f"{cmd} 需要 fleet 序号")
            path = path + [(FLEETS if fleets else ARMIES, fleet)]
            stmt = f"ShipTemplate.{cmd}(MilitaryFormation.Self)"
        else:
            stmt = f"ShipTemplate.{cmd}"
        if cmd == "DeleteTemplate":
            before = [t["name"] for t in self.templates()]
            return self._run(name, stmt, lambda: [t["name"] for t in self.templates()],
                             lambda v: v != before, path=path)
        if cmd in ("QueueConstruction", "QueueConstructionForFleet"):
            before = len(self.ship_constructions())
            return self._run(name, stmt, lambda: len(self.ship_constructions()),
                             lambda v: v > before, path=path)
        if cmd in ("CancelConstruction", "CancelConstructionForFleet"):
            before = len(self.ship_constructions())
            return self._run(name, stmt, lambda: len(self.ship_constructions()),
                             lambda v: v < before, path=path)
        probes = ["ShipTemplate.GetConstructionWeeks", "ShipTemplate.GetNameNoFormatting"]
        return self._run(name, stmt, lambda: _flags(self.b.read_many(probes, self._template_path(index))),
                         None, path=path)

    # ------------------------------------------------------------ 造船队列
    def ship_constructions(self) -> list[dict[str, Any]]:
        """玩家的造船队列（ShipList.GetShipConstructions），按队列顺序。"""
        return [{"index": i, "template": plain(t), "fleet": plain(f),
                 "place": int(float(p or 0)), "weeks": int(float(w or 0)), "in_progress": ip == "1"}
                for i, (t, f, p, w, ip) in enumerate(self.b.rows(f"{SHIP_LIST}.GetShipConstructions",
                                                                 SHIP_CONSTRUCTION_FIELDS))]

    def _ship_construction_path(self, index: int) -> list:
        return [(f"{SHIP_LIST}.GetShipConstructions", index)]

    def ship_construction_action(self, index: int, cmd: str) -> ActionResult:
        """造船队列：Cancel / MoveUp / MoveDown / MoveToTop / MoveToBottom。"""
        path = self._ship_construction_path(index)
        name = f"造船队列 {index}：{cmd}"
        if cmd == "Cancel":
            before = len(self.ship_constructions())
            return self._run(name, "ShipConstruction.Cancel",
                             lambda: len(self.ship_constructions()), lambda v: v == before - 1, path=path)
        if cmd not in ("MoveUp", "MoveDown", "MoveToTop", "MoveToBottom"):
            raise ValueError("cmd 取 Cancel / MoveUp / MoveDown / MoveToTop / MoveToBottom")
        before = [(c["template"], c["fleet"]) for c in self.ship_constructions()]
        return self._run(name, f"ShipConstruction.{cmd}",
                         lambda: [(c["template"], c["fleet"]) for c in self.ship_constructions()],
                         lambda v: v != before, path=path)

    def ship_construction_move(self, index: int, to: int) -> ActionResult:
        """造船队列拖拽（GetDraggedDatacontext('ShipConstruction').MoveToIndex）。"""
        before = [(c["template"], c["fleet"]) for c in self.ship_constructions()]
        return self._run(f"造船队列 {index} → {to}", f"ShipConstruction.MoveToIndex('(int32){to}')",
                         lambda: [(c["template"], c["fleet"]) for c in self.ship_constructions()],
                         lambda v: v != before, path=self._ship_construction_path(index))

    # ------------------------------------------------------------ 舰船选择
    def ship_selection(self) -> dict[str, Any]:
        """舰船列表里的选择状态（ShipList.GetActiveSelection）。"""
        path = [(SHIP_SELECTION, 0)]
        return {"selected": int(float(self._probe("ShipSelection.GetNumShipsSelected", path) or 0)),
                "type": plain(self._probe("ShipSelection.GetTypeOfShipsSelected.GetNameNoFormatting", path)
                              or "")}

    def _ship_group_index(self, ship: int = 0) -> int:
        """舰船所在的 ShipGroup 在 GetShipGroups 里的下标。"""
        key = self._probe("Ship.GetGroup.GetKey", self._ship_path(ship))
        keys = [r[0] for r in self.b.rows(f"{SHIP_LIST}.GetShipGroups", ["ShipGroup.GetKey"])]
        return keys.index(key) if key in keys else 0

    def _ensure_edit_mode(self, group: int) -> None:
        """确保某个舰船组处于编辑模式（选择对象只在编辑模式里存在）。"""
        path = [(f"={SHIP_LIST}", 0), (f"{SHIP_LIST}.GetShipGroups", group)]
        if self._probe("ShipList.IsEditModeActiveForGroup(ShipGroup.Self)", path) != "1":
            self.b.exec("ShipList.ToggleEditMode(ShipGroup.Self)", path=path)

    def select_all_ships(self, ship: int = 0, group: int = -1) -> ActionResult:
        """选中某舰船组里的全部舰船（逐艘 ShipSelection.ToggleSelection）。
        默认用第 ship 艘船所在的组；group 给定时用它。"""
        group = self._ship_group_index(ship) if group < 0 else group
        self._ensure_edit_mode(group)
        rows = self.ships()
        if not rows:
            return ActionResult(False, "全选舰船", "没有舰船")
        key = rows[ship]["group"]
        before = self.ship_selection()
        for i, s in enumerate(rows):
            if s["group"] != key:
                continue
            p = [(SHIP_SELECTION, 0), (f"{SHIP_LIST}.GetShips", i)]
            try:
                if self._probe("ShipSelection.IsSelected(Ship.Self)", p) == "1":
                    continue
            except GameError:
                pass
            self.b.exec("ShipSelection.ToggleSelection(Ship.Self)", path=p)
        after = self.ship_selection()
        return ActionResult(after["selected"] > before["selected"], "全选舰船", "", before, after)

    def ship_selection_action(self, cmd: str, template: int = -1, ship: int = 0,
                              group: int = -1) -> ActionResult:
        """对选中的舰船执行：Retrofit / Decommission / ChangeTemplate(template)。"""
        group = self._ship_group_index(ship) if group < 0 else group
        self._ensure_edit_mode(group)
        path = [(SHIP_SELECTION, 0)]
        name = f"选中舰船：{cmd}"
        if cmd == "ChangeTemplate":
            if template < 0:
                raise ValueError("ChangeTemplate 需要 template")
            path = path + self._template_path(template)
            stmt = "ShipSelection.ChangeTemplate(ShipTemplate.Self)"
        else:
            stmt = f"ShipSelection.{cmd}"
        if cmd == "Decommission":
            before = len(self.ships())
            return self._run(name, stmt, lambda: len(self.ships()), lambda v: v == before - 1, path=path)
        return self._run(name, stmt, self.ship_selection, None, path=path)

    def panel_upgrade_all(self) -> ActionResult:
        """军事面板的「升级全部编队里的全部单位」——按编队逐个执行
        MilitaryFormation.GetUpgradeAllUnitsCommand（与面板按钮最终走的是同一条命令）。"""
        done = []
        for fleets in (False, True):
            for i, f in enumerate(self.formations(fleets)):
                r = self.upgrade_all(i, fleets)
                if r.ok:
                    done.append(f["name"])
        return ActionResult(bool(done), "升级全部编队里的全部单位", "、".join(done) or "没有可升级单位")

    def decommission_supply_ships(self, count: int = 1) -> ActionResult:
        """退役补给舰——补给舰窗口的等价路径：逐个执行 Ship.Decommission。
        只退役名字/类型里带「补给」的舰船，最多 count 艘。"""
        targets = [(i, s) for i, s in enumerate(self.ships())
                   if "补给" in s["type"] or "supply" in s["type"].lower()]
        if not targets:
            return ActionResult(False, "退役补给舰", "没有补给舰")
        done = 0
        for _, s in targets[:count]:
            # 退役后列表会重排：每艘按名字重新找下标
            i = next((j for j, x in enumerate(self.ships()) if x["name"] == s["name"]), None)
            if i is not None and self.ship_action(i, "Decommission").ok:
                done += 1
        return ActionResult(done > 0, f"退役补给舰 {done} 艘", f"共 {len(targets)} 艘补给舰")

    def building_type_toggle_all(self, key: str, cmd: str) -> ActionResult:
        """建筑浏览器按类型批量操作：ToggleAllSubsidies / ToggleAllAutoExpand /
        ToggleAllPrivatization / RemoveAllPrivatization——按州逐个建筑执行对应命令。
        cmd 取 Subsidies / AutoExpand / Privatization。"""
        mapping = {"Subsidies": "ToggleSubsidies", "AutoExpand": "ToggleAutoExpand",
                   "Privatization": "TogglePrivatization", "RemoveAllPrivatization": "TogglePrivatization"}
        if cmd not in mapping:
            raise ValueError(f"cmd 取 {list(mapping)}")
        bs = self.b
        states = bs.rows("AccessMetaPlayer.AccessPlayedOrObservedCountry.AccessStates",
                         ["State.GetID", "State.GetNameNoFormatting"])
        done = 0
        for sid, name in states:
            sp = [(f"{PLAYER_MUT}.AccessStates", list(map(lambda r: r[0], states)).index(sid))]
            keys = [r[0] for r in bs.rows("State.AccessBuildings", ["Building.GetBuildingType.GetKey"], path=sp)]
            for bi, k in enumerate(keys):
                if k != key:
                    continue
                r = self.building_action(int(sid), key, mapping[cmd])
                if r.ok:
                    done += 1
        return ActionResult(done > 0, f"{key}：{cmd}", f"操作了 {done} 个建筑")

    # ------------------------------------------------------------ 借调设置
    def borrow_settings(self, index: int, fleets: bool = False) -> list[dict[str, Any]]:
        """编队的「允许友方借调」设置（MilitaryFormation.GetBorrowSettings）。"""
        path = self._formation_path(index, fleets)
        return [{"index": i, "name": plain(n), "selected": s == "1"}
                for i, (n, s) in enumerate(self.b.rows(
                    "MilitaryFormation.GetBorrowSettings",
                    ["MilitaryFormationBorrowSetting.GetName", "MilitaryFormationBorrowSetting.IsSelected"],
                    path=path))]

    def borrow_setting(self, index: int, setting: int, fleets: bool = False) -> ActionResult:
        """切换借调设置：先 OnClicked（界面按钮的第一个回调，更新选中的设置），
        再 Execute(GetBorrowingCommand)。"""
        path = self._formation_path(index, fleets) + [("MilitaryFormation.GetBorrowSettings", setting)]
        name = plain(self._probe("MilitaryFormationBorrowSetting.GetName", path) or setting)
        self.b.exec("MilitaryFormationBorrowSetting.OnClicked", path=path)
        return self._run(f"借调设置 → {name[:24]}", "MilitaryFormationBorrowSetting.GetBorrowingCommand",
                         lambda: [self._probe("MilitaryFormationBorrowSetting.IsSelected", path)],
                         lambda v: v == ["1"], path=path)

    # ------------------------------------------------------------ 指挥部 / 前线 / 入侵
    def hq_action(self, formation: int, cmd: str = "GetStationSelectedFormationsCommand",
                  fleets: bool = False) -> ActionResult:
        """指挥部命令：把选中的编队驻扎到该编队的 HQ（Hq.GetStationSelectedFormationsCommand）。"""
        path = self._formation_path(formation, fleets) + [("=MilitaryFormation.GetHomeHQ", 0)]
        name = f"指挥部驻扎（编队 {formation}）"
        probes = ["Hq.GetName", "MilitaryFormation.IsSelected"]
        return self._run(name, f"Hq.{cmd}",
                         lambda: _flags(self.b.read_many(probes, path)), None, path=path)

    def front_action(self, war: int, cmd: str = "GetDeploySelectedFormationsCommand") -> ActionResult:
        """前线命令（War.AccessFronts 里的第 war 个前线）。"""
        path = [(f"{PLAYER_MUT}.AccessWars", war), ("War.AccessFronts", 0)]
        name = f"战争 {war} 的前线：{cmd}"
        probes = ["Front.GetNameNoFormatting", "Front.GetPlayerSideCombatUnitsBreakdown"]
        return self._run(name, f"Front.{cmd}",
                         lambda: _flags(self.b.read_many(probes, path)), None, path=path)

    def invasions(self, war: int) -> list[dict[str, Any]]:
        """战争中的入侵（War.GetInvasions）。"""
        path = [(f"{PLAYER_MUT}.AccessWars", war)]
        return [{"index": i, "state": plain(s), "invader": plain(c)}
                for i, (s, c) in enumerate(self.b.rows("War.GetInvasions",
                                                       ["Invasion.GetTargetState.GetNameNoFormatting",
                                                        "Invasion.GetInvaderCountry.GetNameNoFormatting"],
                                                       path=path))]

    def invasion_action(self, war: int, index: int, cmd: str, formation: int = -1,
                        fleets: bool = False) -> ActionResult:
        """入侵命令：Cancel / DeployArmyToDefend(formation) / DeployFleetToDefend(formation) /
        GetDeploySelectedFormationsCommand。"""
        path = [(f"{PLAYER_MUT}.AccessWars", war), ("War.GetInvasions", index)]
        if cmd in ("DeployArmyToDefend", "DeployFleetToDefend"):
            if formation < 0:
                raise ValueError(f"{cmd} 需要 formation 序号")
            path = path + [(FLEETS if fleets else ARMIES, formation)]
            stmt = f"Invasion.{cmd}(MilitaryFormation.Self)"
        else:
            stmt = f"Invasion.{cmd}"
        name = f"入侵 {index}：{cmd}"
        probes = ["Invasion.GetTargetState.GetNameNoFormatting"]
        return self._run(name, stmt, lambda: _flags(self.b.read_many(probes, path)), None, path=path)

    # ------------------------------------------------------------ 建筑类型 / 军事建造
    def building_type_action(self, key: str, cmd: str = "ToggleMonopoly") -> ActionResult:
        """建筑类型上的命令（建筑浏览器右键菜单）：ToggleMonopoly。key 是 building_*。"""
        path = [(f"=GetBuildingType('{key}')", 0)]
        probe = f"BuildingType.GetMonopolyCountryIn({PLAYER}).GetTagName"
        return self._run(f"{key}：{cmd}", f"BuildingType.{cmd}",
                         lambda: [plain(self._probe(probe, path) or "")], None, path=path)

    def queue_military_construction(self, state: int, building: str, formation: int,
                                    unit_type: str, fleets: bool = False) -> ActionResult:
        """在军事建筑上排产（建筑面板的「建造军队」）：
        Building.QueueMilitaryConstruction(MilitaryFormation.Self, CombatUnitType.Self)。"""
        spath, why = self._building_path(state, building)
        if not spath:
            return ActionResult(False, f"{building} @ {state}：军事建造", why)
        path = spath + [(FLEETS if fleets else ARMIES, formation),
                        (f"=GetCombatUnitType('{unit_type}')", 0)]
        before = int(float(self._probe("Building.GetExpansionLevelsInQueue", spath) or 0))
        return self._run(f"{building} @ {state}：军事建造 {unit_type}",
                         "Building.QueueMilitaryConstruction(MilitaryFormation.Self,CombatUnitType.Self)",
                         lambda: int(float(self._probe("Building.GetExpansionLevelsInQueue", spath) or 0)),
                         lambda v: v > before, path=path)

    # ------------------------------------------------------------ 窗口对象 / 改名
    _PID: int | None = None
    _VTABLES = {
        # 1.13.11 的 vtable RVA（RTTI: .?AVCAddWarGoalPanel@@ 等，见 docs/bridge.md）
        "AddWarGoalPanel": 0x45B79E0,
        "SwayCountryPanel": 0x45E1CE8,
        "TransferFormationPopup": 0x45E7440,
        "PowerBlocFormation": 0x45D3D38,
    }

    def _info_bar_ptr(self) -> int:
        return int.from_bytes(self.b.eval_raw("InformationPanelBar.AccessSelf")[8:16], "little")

    def _scan_vtable(self, rva: int, near: int | None = None, radius: int = 0x8000000) -> list[int]:
        """在游戏进程里找第一个字段是指定 vtable 的对象（窗口单例）。near 给定时只扫附近。"""
        class MBI(ctypes.Structure):
            _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                        ("AllocationProtect", ctypes.c_uint32), ("PartitionId", ctypes.c_uint16),
                        ("RegionSize", ctypes.c_size_t), ("State", ctypes.c_uint32),
                        ("Protect", ctypes.c_uint32), ("Type", ctypes.c_uint32)]

        target = (int(self.b.health()["base"], 16) + rva).to_bytes(8, "little")
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        h = k.OpenProcess(0x0410, False, self._pid())
        if not h:
            raise GameError(f"OpenProcess 失败：{ctypes.get_last_error()}")
        start = max(0, near - radius) if near else 0
        end = min(0x7FFF_FFFF_FFFF, near + radius) if near else 0x7FFF_FFFF_FFFF
        addr, found = start, []
        while addr < end:
            mbi = MBI()
            if not k.VirtualQueryEx(h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
                break
            size = mbi.RegionSize
            if mbi.State == 0x1000 and (mbi.Protect & 0xCC) and 0 < size <= 0x4000000:
                buf = ctypes.create_string_buffer(size)
                n = ctypes.c_size_t(0)
                if k.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, size, ctypes.byref(n)):
                    data = buf.raw[:n.value]
                    i = 0
                    while len(found) < 8:
                        i = data.find(target, i)
                        if i < 0:
                            break
                        found.append(addr + i)
                        i += 1
            addr += size or 0x1000
        k.CloseHandle(h)
        return found

    def add_war_goal(self, play: int = 0, type_index: int = 0, goal_index: int = 0) -> ActionResult:
        """外交博弈面板的「添加战争目标」：开 AddWarGoalPanel，选类型，点 AddWarGoal。"""
        play_path = [(PLAYS, play)]
        try:
            self.b.exec("InformationPanelBar.OpenAddWarGoalPanel(DiplomaticPlay.Self,GetPlayer.Self)", path=play_path)
        except GameError as e:
            return ActionResult(False, "添加战争目标", f"打开面板失败：{e}")
        time.sleep(0.25)
        try:
            panel = self._scan_vtable(self._VTABLES["AddWarGoalPanel"], near=self._info_bar_ptr())[0]
        except IndexError:
            return ActionResult(False, "添加战争目标", "没找到 AddWarGoalPanel 对象")
        pp = [(f"=@{panel:x}", 0)]
        tl, dl = "AddWarGoalPanel.AccessShownWarGoalTypes", "AddWarGoalPanel.AccessShownWarGoals"
        types = [plain(r[0]) for r in self.b.rows(tl, ["WarGoalType.GetNameNoFormatting"], path=pp)]
        if type_index >= len(types):
            self._close_panel()
            return ActionResult(False, "添加战争目标", f"可选类型：{types}")
        self.b.exec("AddWarGoalPanel.SetSelectedWarGoalType(WarGoalType.Self)", path=pp + [(tl, type_index)])
        time.sleep(0.2)
        drafts = self.b.rows(dl, ["WarGoalDraft.GetNameNoFormatting"], path=pp)
        if goal_index >= len(drafts):
            self._close_panel()
            return ActionResult(False, f"添加战争目标 {types[type_index]}", f"只有 {len(drafts)} 个可选目标")
        dp = play_path + pp + [(dl, goal_index)]
        before = len(self.b.rows("DiplomaticPlay.GetInitiatorWarGoals", ["WarGoal.GetName"], path=play_path))
        r = self._run(f"战争目标：{types[type_index]} #{goal_index}",
                      "DiplomaticPlay.AddWarGoal(WarGoalDraft.Self)",
                      lambda: len(self.b.rows("DiplomaticPlay.GetInitiatorWarGoals", ["WarGoal.GetName"],
                                              path=play_path)),
                      lambda v: v > before, path=dp)
        self._close_panel()
        return r

    def _close_panel(self) -> None:
        try:
            self.b.exec("InformationPanelBar.ClosePanel")
        except GameError:
            pass

    def create_sway(self, play: int = 0, country: str = "", type_index: int = -1,
                    offer: int = -1) -> ActionResult:
        """诱导第三国（SwayCountryPanel.CreateSway）：开面板，必要时选提议类型，逐个试可用提议。"""
        try:
            self.b.exec("InformationPanelBar.OpenSwayCountryPanel(DiplomaticPlay.Self,Country.Self)",
                        path=[(PLAYS, play), (self.country_ref(country), 0)])
        except GameError as e:
            return ActionResult(False, f"诱导 {country}", f"打开面板失败：{e}")
        time.sleep(0.25)
        found = self._scan_vtable(self._VTABLES["SwayCountryPanel"])
        if not found:
            return ActionResult(False, f"诱导 {country}", "没找到 SwayCountryPanel 对象")
        pp = [(f"=@{found[0]:x}", 0)]
        tl, ol = "SwayCountryPanel.AccessSwayOfferTypes", "SwayCountryPanel.AccessShownSwayOffers"
        if type_index >= 0:
            self.b.exec("SwayCountryPanel.SetSwayOfferType(SwayOfferType.Self)", path=pp + [(tl, type_index)])
        stmt = ("SwayCountryPanel.AccessDiplomaticPlay.CreateSway("
                "GetPlayer.Self,SwayCountryPanel.GetCountry,SwayOffer.Self)")
        indices = [offer] if offer >= 0 else range(len(self.b.rows(ol, ["SwayOffer.RequiresAnyInput"], path=pp)))
        for i in indices:
            p = pp + [(ol, i)]
            if self._probe(f"IsValid({stmt})", p) == "1":
                return self._run(f"诱导 {country}", stmt,
                                 lambda: [self._probe("DiplomaticPlay.GetOutgoingSway(GetPlayer.Self,"
                                                      "SwayCountryPanel.GetCountry).IsValid",
                                                      [(PLAYS, play)] + pp)], None, path=p)
        self._close_panel()
        return ActionResult(False, f"诱导 {country}",
                            "当前没有可用提议（需要博弈开局阶段 / 对方接受度 / maneuver）")

    def transfer_formation(self, left: int, right: int = -1, fleets: bool = False) -> ActionResult:
        """编队之间转移单位（TransferFormationPopup.Confirm）：开弹窗，设右侧编队，再看是否就绪。"""
        path = self._formation_path(left, fleets)
        popup = self._popup_after_open("PopupManager.ShowTransferFormation(MilitaryFormation.AccessSelf)",
                                       path)
        pp = [(f"=@{popup:x}", 0)]
        if right >= 0:
            try:
                self.b.exec("TransferFormationPopup.SetSelectedRightFormation(MilitaryFormation.Self)",
                            path=pp + self._formation_path(right, fleets))
            except GameError:
                pass
        if self._probe("IsValid(TransferFormationPopup.Confirm)", pp) != "1":
            return ActionResult(False, f"编队转移 {left}→{right}",
                                "右侧编队/待转移单位没有就绪（StagedFormation 选择层）")
        return self._run(f"编队转移 {left}→{right}", "TransferFormationPopup.Confirm",
                         lambda: [self._probe("TransferFormationPopup.HasRightFormation", pp)], None, path=pp)

    def power_bloc_formation(self) -> ActionResult:
        """成立权力集团（PowerBlocFormation.Confirm）：开面板，确认默认身份/原则是否已就绪。"""
        try:
            self.b.exec("InformationPanelBar.OpenPowerBlocFormationPanel")
        except GameError as e:
            return ActionResult(False, "成立权力集团", f"打开面板失败：{e}")
        time.sleep(0.3)
        found = self._scan_vtable(self._VTABLES["PowerBlocFormation"])
        if not found:
            return ActionResult(False, "成立权力集团", "没找到 PowerBlocFormation 对象")
        pp = [(f"=@{found[0]:x}", 0)]
        if self._probe("IsValid(PowerBlocFormation.Confirm)", pp) != "1":
            n = self._probe("PowerBlocFormation.GetNumSelectedPrinciples", pp)
            return ActionResult(False, "成立权力集团", f"面板还需选原则（已选 {n} 个）")
        before = self.bloc().get("in_bloc")
        return self._run("成立权力集团", "PowerBlocFormation.Confirm",
                         lambda: [str(self.bloc().get("in_bloc"))], lambda v: v == ["True"], path=pp)

    def ship_designer_create(self, edit: bool = False, template: int = -1) -> ActionResult:
        """造船设计器的新建/编辑模板（ShipDesignerPopup.CreateTemplate/EditTemplate）。"""
        pp = [("=PopupManager.AccessShipDesignerPopup.Self", 0)]
        try:
            if template >= 0:
                tp = self._template_path(template)
                self.b.exec("PopupManager.ToggleShipDesignerPopupWithTemplate(ShipTemplate.Self)", path=tp)
                time.sleep(0.2)
                self.b.exec("ShipDesignerPopup.SetShipTemplate(ShipTemplate.Self)", path=pp + tp)
            else:
                self.b.exec("PopupManager.ToggleShipDesignerPopup")
        except GameError as e:
            return ActionResult(False, "造船设计器", f"打开失败：{e}")
        time.sleep(0.25)
        cmd = "ShipDesignerPopup.EditTemplate" if edit else "ShipDesignerPopup.CreateTemplate"
        if self._probe(f"IsValid({cmd})", pp) != "1":
            return ActionResult(False, "造船设计器",
                                "不可执行（HasDlcFeature('ship_designer')=0 或模板/舰种未选）")
        before = len(self.templates())
        if edit:
            probe = lambda: [self._probe("ShipDesignerPopup.GetTemplateEdited.GetNameNoFormatting", pp)]   # noqa: E731
            return self._run("编辑舰船模板", cmd, probe, None, path=pp)
        return self._run("新建舰船模板", cmd, lambda: len(self.templates()), lambda v: v > before, path=pp)

    def _pid(self) -> int:
        if Coverage._PID is None:
            Coverage._PID = int(self.b.health()["pid"])
        return Coverage._PID

    def _write_mem(self, addr: int, data: bytes) -> None:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        h = k.OpenProcess(0x1F0FFF, False, self._pid())
        if not h:
            raise GameError(f"OpenProcess 失败：{ctypes.get_last_error()}")
        n = ctypes.c_size_t(0)
        ok = k.WriteProcessMemory(h, ctypes.c_void_p(addr), data, len(data), ctypes.byref(n))
        k.CloseHandle(h)
        if not ok:
            raise GameError(f"写内存 {hex(addr)} 失败：{ctypes.get_last_error()}")

    def _alloc_mem(self, size: int) -> int:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        h = k.OpenProcess(0x1F0FFF, False, self._pid())
        if not h:
            raise GameError(f"OpenProcess 失败：{ctypes.get_last_error()}")
        addr = k.VirtualAllocEx(h, None, size, 0x3000, 0x04)
        k.CloseHandle(h)
        if not addr:
            raise GameError(f"VirtualAllocEx 失败：{ctypes.get_last_error()}")
        return int(addr)

    def _popup_after_open(self, opener: str, path: list) -> int:
        """开一个 PopupManager 弹窗，返回它在 PopupManager 里的新指针（对比前后内存）。"""
        pm = int.from_bytes(self.b.eval_raw("PopupManager.AccessSelf")[8:16], "little")
        before = self.b.mem_read(pm, 0x800)
        self.b.exec(opener, path=path)
        time.sleep(0.25)
        after = self.b.mem_read(pm, 0x800)
        for off in range(0, 0x800, 8):
            if before[off:off + 8] != after[off:off + 8]:
                cand = int.from_bytes(after[off:off + 8], "little")
                if cand > 0x1_0000_0000:
                    return cand
        raise GameError("打开窗口后没有在 PopupManager 里找到新对象")

    def _rename_in_popup(self, popup: int, new_name: str) -> None:
        """弹窗里的名字是 std::string：+0x90 是缓冲区/指针，+0xa0 是长度，+0xa8 是容量。"""
        raw = new_name.encode("utf-8")
        ptr = int.from_bytes(self.b.mem_read(popup + 0x90, 8), "little")
        cap = int.from_bytes(self.b.mem_read(popup + 0xa8, 8), "little")
        if len(raw) > cap:
            buf = self._alloc_mem(len(raw) + 1)
            self._write_mem(buf, raw + b"\0")
            self._write_mem(popup + 0x90, buf.to_bytes(8, "little"))
            self._write_mem(popup + 0xa8, (len(raw) + 1).to_bytes(8, "little"))
        elif cap <= 15:
            self._write_mem(popup + 0x90, raw.ljust(16, b"\0"))
        else:
            self._write_mem(ptr, raw + b"\0")
        self._write_mem(popup + 0xa0, len(raw).to_bytes(8, "little"))

    def _confirm_popup(self, popup: int, name: str, cmd: str, probe, expect) -> ActionResult:
        return self._run(name, cmd, probe, expect, path=[(f"=@{popup:x}", 0)])

    def rename_company(self, key: str, new_name: str) -> ActionResult:
        """公司改名弹窗（CompanyChangeNamePopup.Confirm）。"""
        from agent.actions import COMPANIES
        keys = [r[0] for r in self.b.rows(COMPANIES, ["Company.GetCompanyType.GetKey"])]
        if key not in keys:
            return ActionResult(False, f"公司改名 {key}", f"没有这个公司：{keys}")
        popup = self._popup_after_open("PopupManager.ShowCompanyChangeName(Company.Self)",
                                       [(COMPANIES, keys.index(key))])
        self._rename_in_popup(popup, new_name)
        probe = lambda: [plain(r[0]) for r in self.b.rows(COMPANIES, ["Company.GetNameNoFormatting"])]   # noqa: E731
        return self._confirm_popup(popup, f"公司改名 → {new_name}", "CompanyChangeNamePopup.Confirm",
                                   probe, lambda v: new_name in v)

    def rename_formation(self, index: int, new_name: str, fleets: bool = False) -> ActionResult:
        """编队改名弹窗（MilitaryFormationChangeNamePopup.Confirm）。"""
        popup = self._popup_after_open("PopupManager.ShowMilitaryFormationChangeName(MilitaryFormation.Self)",
                                       self._formation_path(index, fleets))
        self._rename_in_popup(popup, new_name)
        probe = lambda: [f["name"] for f in self.formations(fleets)]   # noqa: E731
        return self._confirm_popup(popup, f"编队改名 → {new_name}",
                                   "MilitaryFormationChangeNamePopup.Confirm", probe,
                                   lambda v: new_name in v)

    def rename_ship(self, index: int, new_name: str, fleet: int = -1, fleets: bool = False) -> ActionResult:
        """舰船改名弹窗（ShipChangeNamePopup.Confirm）。舰船列表会按名字重排，核实时看全表。"""
        popup = self._popup_after_open("PopupManager.ShowShipChangeName(Ship.Self)",
                                       self._ship_path(index, fleet, fleets))
        self._rename_in_popup(popup, new_name)
        probe = lambda: [s["name"] for s in self.ships(fleet, fleets)]   # noqa: E731
        return self._confirm_popup(popup, f"舰船改名 → {new_name}", "ShipChangeNamePopup.Confirm",
                                   probe, lambda v: new_name in v)

    def rename_state(self, state: int | str, new_name: str) -> ActionResult:
        """州改名弹窗（StateNameChangePopup.Confirm）。"""
        sp = self._state_path(state)
        if not sp:
            return ActionResult(False, f"州改名 {state}", f"玩家没有州 {state}")
        popup = self._popup_after_open("PopupManager.ShowStateChangeName(State.Self)", sp)
        self._rename_in_popup(popup, new_name)
        probe = lambda: [self._probe("State.GetNameNoFormatting", sp)]   # noqa: E731
        return self._confirm_popup(popup, f"州改名 → {new_name}", "StateNameChangePopup.Confirm",
                                   probe, lambda v: v == [new_name])

    def rename_prestige_good(self, company: str, index: int, new_name: str) -> ActionResult:
        """奢侈品改名弹窗（PrestigeGoodChangeNamePopup.Confirm）。company 是公司类型 key。"""
        from agent.actions import COMPANIES
        keys = [r[0] for r in self.b.rows(COMPANIES, ["Company.GetCompanyType.GetKey"])]
        if company not in keys:
            return ActionResult(False, f"奢侈品改名 {company}", f"没有这个公司：{keys}")
        cpath = [(COMPANIES, keys.index(company))]
        goods = self.b.rows("Company.GetPrestigeGoods", ["PrestigeGood.GetNameNoFormatting"], path=cpath)
        if index >= len(goods):
            return ActionResult(False, f"奢侈品改名 {company}", f"只有 {len(goods)} 个奢侈品")
        gpath = cpath + [("Company.GetPrestigeGoods", index)]
        popup = self._popup_after_open("PopupManager.ShowPrestigeGoodChangeName(PrestigeGood.Self)", gpath)
        self._rename_in_popup(popup, new_name)
        probe = lambda: [self._probe("PrestigeGood.GetNameNoFormatting", gpath)]   # noqa: E731
        return self._confirm_popup(popup, f"奢侈品改名 → {new_name}", "PrestigeGoodChangeNamePopup.Confirm",
                                   probe, lambda v: v == [new_name])

    # ------------------------------------------------------------ 海峡
    def _strait_ptr(self) -> int | None:
        if not hasattr(self, "_strait_ptrs"):
            self._strait_ptrs = self._scan_vtable(0x4490548)   # 1.13.11 CStrait vtable
        return self._strait_ptrs[0] if self._strait_ptrs else None

    def strait_action(self, kind: str, value: str, index: int = -1) -> ActionResult:
        """海峡命令：kind=toll/access/allowed，value 是档位（NoTolls/LowTolls/...、
        Open/NoMilitary/Closed、OnlyController/OnlyAllies/NoEnemies）。
        命令只在玩家『完全控制』海峡时可用；没完全控制时返回原因。"""
        if not hasattr(self, "_strait_ptrs"):
            self._strait_ptrs = self._scan_vtable(0x4490548)   # 1.13.11 CStrait vtable
        ptrs = self._strait_ptrs
        if not ptrs:
            return ActionResult(False, f"海峡 {kind} {value}", "没有找到 CStrait 对象")
        ptr = ptrs[index] if 0 <= index < len(ptrs) else ptrs[0]
        sp = [(f"=@{ptr:x}", 0)]
        cp, stp = sp + [(f"={PLAYER}", 0)], sp + [("=Strait.GetFirstState", 0)]
        if kind == "toll":
            cmd = f"Strait.SetControllerTollRate{value}(Country.Self)"
            probe = f"Strait.ControllerHasTollRate{value}(Country.Self)"
            path = cp
        elif kind == "access":
            cmd = f"Strait.SetStateAccess{value}(State.Self)"
            probe = f"Strait.StateHasAccess{value}(State.Self)"
            path = stp
        elif kind == "allowed":
            cmd = f"Strait.SetStateAllowedCountries{value}(State.Self)"
            probe = f"Strait.StateHasAllowedCountries{value}(State.Self)"
            path = stp
        else:
            raise ValueError("kind 取 toll / access / allowed")
        if self._probe(f"IsValid({cmd})", path) != "1":
            full = self._probe("Strait.IsFullController(Country.Self)", cp)
            return ActionResult(False, f"海峡 {kind} {value}",
                                f"不可用（需要完全控制；当前 IsFullController={full}）")
        return self._run(f"海峡 {kind} {value}", cmd, lambda: [self._probe(probe, path)],
                         lambda v: v == ["1"], path=path)

    # ------------------------------------------------------------ 君主
    def _open_ruler_popup(self) -> int:
        try:
            self.b.exec("PopupManager.HideRulerSelectionPopup")
        except GameError:
            pass
        time.sleep(0.1)
        return self._popup_after_open("PopupManager.ShowRulerSelectionPopup(Country.Self)",
                                      [(f"={PLAYER}", 0)])

    def randomize_ruler(self) -> ActionResult:
        """随机刷新君主候选人（RulerSelectionPopup.RandomizeRulersOffer）。"""
        popup = self._open_ruler_popup()
        pp = [(f"=@{popup:x}", 0)]
        probe = lambda: [plain(r[0]) for r in self.b.rows(   # noqa: E731
            "RulerSelectionPopup.AccessRulersOffer", ["Character.GetFullName"], path=pp)]
        return self._run("随机君主候选人", "RulerSelectionPopup.RandomizeRulersOffer", probe, None, path=pp)

    def set_ruler(self, offer: int = 0) -> ActionResult:
        """从候选人里任命君主（RulerSelectionPopup.SetRulerCommand(Character.Self)）。"""
        popup = self._open_ruler_popup()
        pp = [(f"=@{popup:x}", 0)]
        ol = "RulerSelectionPopup.AccessRulersOffer"
        offers = self.b.rows(ol, ["Character.GetFullName"], path=pp)
        if offer >= len(offers):
            return ActionResult(False, f"任命君主 {offer}", f"只有 {len(offers)} 个候选人")
        name = plain(offers[offer][0])
        cp = [(f"={PLAYER}", 0)]
        before = self._probe("Country.GetRuler.GetFullName", cp)
        return self._run(f"任命君主 {name}", "RulerSelectionPopup.SetRulerCommand(Character.Self)",
                         lambda: [self._probe("Country.GetRuler.GetFullName", cp)],
                         lambda v: v != [before], path=pp + [(ol, offer)])

    # ------------------------------------------------------------ 登船 / 运输（伪造包装）
    def embark_formation(self, army: int, fleet: int, fleets: bool = True) -> ActionResult:
        """把陆军装上舰队（MilitaryFormationWrapped.EmbarkFormation）：
        MilitaryFormationWrapped 就是一个 {MilitaryFormation*}，用 /data/fake 在偏移 0 放陆军。"""
        ap, fp = [(ARMIES, army)], [(FLEETS, fleet)]
        spec = "0:0:q=c0"
        try:
            ok = self.b.read_fake(
                "[IsValid(MilitaryFormationWrapped.EmbarkFormation(MilitaryFormation.Self))]", spec, path=ap + fp)
        except GameError as e:
            return ActionResult(False, f"登船 {army}→{fleet}", str(e)[:200])
        if ok != "1":
            return ActionResult(False, f"登船 {army}→{fleet}", "游戏判定不可用")
        probe = lambda: [self._probe("MilitaryFormation.HasTransportedArmyOnboard", fp),   # noqa: E731
                         self._probe("MilitaryFormation.GetTransportMissionQueueCount", fp)]
        before = probe()
        self.b.exec_fake("Execute(MilitaryFormationWrapped.EmbarkFormation(MilitaryFormation.Self))",
                         spec, path=ap + fp)
        return self._settle(f"登船 {army}→{fleet}", probe, before)

    # ------------------------------------------------------------ 剧本界面 / 忽略
    def scripted_gui(self, name: str) -> ActionResult:
        """剧本界面的按钮（GetScriptedGui('名字').Execute(...)）。"""
        stmt = f"GetScriptedGui('{name}').Execute(GetPlayer)"
        return self._run(f"剧本按钮 {name}", stmt, lambda: [str(self._signature())], None)

    def toggle_ignore_decision(self, decision: str) -> ActionResult:
        """在日志/决议里忽略一条决议（GetPlayer.ToggleIgnoreDecision(Decision.Self)）。"""
        names = [plain(r[0]) for r in self.b.rows(f"{PLAYER_MUT}.GetDecisions", ["Decision.GetName"])]
        if decision not in names:
            return ActionResult(False, f"忽略决议「{decision}」", f"没有这个决议：{names}")
        path = [(f"{PLAYER_MUT}.GetDecisions", names.index(decision))]
        return self._run(f"忽略决议「{decision}」",
                         f"{PLAYER}.ToggleIgnoreDecision(Decision.Self)",
                         lambda: [str(self._signature())], None, path=path)

    def toggle_ignore_formation(self, formation: str) -> ActionResult:
        """在统一运动里忽略一个可成立国家（GetPlayer.ToggleIgnoreCountryFormation）。"""
        from agent.actions import FORMABLE
        names = [plain(r[0]) for r in self.b.rows(FORMABLE, ["CountryFormation.GetName"])]
        if formation not in names:
            return ActionResult(False, f"忽略成立「{formation}」", f"可成立的：{names}")
        path = [(FORMABLE, names.index(formation))]
        return self._run(f"忽略成立「{formation}」",
                         f"{PLAYER}.ToggleIgnoreCountryFormation(CountryFormation.Self)",
                         lambda: [str(self._signature())], None, path=path)
