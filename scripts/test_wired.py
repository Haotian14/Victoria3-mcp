"""逐条实测 actions.json 里状态为「已接」的命令，结果写 logs/coverage_test.json。

用法（游戏已进局、桥接层在线）：
    $env:V3MCP_URL='http://127.0.0.1:8771'
    python scripts/test_wired.py

每条命令给一个当前测试局里能找到的目标；返回 ok=True 表示执行后读到了效果，
ok=False 表示命令下发但游戏判定不可用 / 状态不满足，error 表示测试代码本身抛异常。
"""

from __future__ import annotations

import json
import logging
import os
import sys
import traceback

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

from agent.bridge import GameError, PLAYER_MUT  # noqa: E402
from agent.coverage import Coverage  # noqa: E402

OUT = os.path.join(ROOT, "logs", "coverage_test.json")
ARMIES = f"{PLAYER_MUT}.GetMilitaryFormationsArmy"
FLEETS = f"{PLAYER_MUT}.GetMilitaryFormationsFleet"


def _norm(r):
    if hasattr(r, "ok"):
        return {"ok": r.ok, "action": r.action, "detail": r.detail,
                "before": r.before, "after": r.after}
    return {"ok": True, "result": r}


def _embark(a):
    for ai in range(len(a.formations())):
        for fi in range(len(a.formations(True))):
            try:
                v = a.b.read_fake("[IsValid(MilitaryFormationWrapped.EmbarkFormation("
                                  "MilitaryFormation.Self))]", "0:0:q=c0", path=[(ARMIES, ai), (FLEETS, fi)])
            except Exception:
                v = "0"
            if v == "1":
                return a.embark_formation(ai, fi)
    return a.embark_formation(0, 0)


def run_key(a: Coverage, key: str):
    recv, cmd = key.split(".", 1)
    if recv == "Strait":
        if cmd.startswith("SetControllerTollRate"):
            return a.strait_action("toll", cmd[len("SetControllerTollRate"):])
        if cmd.startswith("SetStateAccess"):
            return a.strait_action("access", cmd[len("SetStateAccess"):])
        if cmd.startswith("SetStateAllowedCountries"):
            return a.strait_action("allowed", cmd[len("SetStateAllowedCountries"):])
    if recv == "Global":
        if cmd in ("MergeSelectedFormations", "SetStrategicObjectiveForSelectedFormations"):
            return a.selected_action(cmd, state_path=a._state_path(5))
        if cmd == "MobilizeSelectedArmies":
            return a.formation_action(0, "Mobilize")
        if cmd == "DemobilizeSelectedArmies":
            return a.formation_action(0, "Demobilize")
        if cmd == "RaiseConscriptsInSelectedArmies":
            return a.formation_action(0, "RaiseConscripts")
        if cmd == "RetrofitShips":
            return a.formation_action(0, "RetrofitShips", fleets=True)
        if cmd == "RetrofitShipsAndStation":
            return a.formation_action(0, "RetrofitShipsAndStation", fleets=True)
        if cmd == "CancelRetrofitShips":
            return a.formation_action(0, "CancelRetrofitShips", fleets=True)
        if cmd == "CreateNavalMissionsForSelectedFleets":
            return a.naval_mission_action(0, 0)
        if cmd == "RemoveNavalMissionForSelectedFleets":
            return a.formation_action(0, "RemoveNavalMission", fleets=True)
        if cmd == "SetCharacterOrderForSelectedFormations":
            return a.commander_action(0, "Order", target=0)
    if recv == "State":
        return a.selected_action("GetStationSelectedFormationsCommand")
    if recv == "MobilizationOption":
        return a.mobilization_action(0, 0)
    if recv == "Ship":
        return a.ship_action(100, cmd, template=1)
    if recv == "ShipTemplate":
        return a.template_action(0, cmd, fleet=0, fleets=True)
    if recv == "ShipSelection":
        a.select_all_ships(0)
        return a.ship_selection_action(cmd, template=1)
    if recv == "ShipConstruction":
        # 移动/取消前先补一个队列项（前面的 Cancel 可能把唯一一项清掉）
        try:
            a.template_action(1, "QueueConstruction")
        except Exception:
            pass
        return a.ship_construction_action(0, cmd)
    if recv == "GetDraggedDatacontext":
        try:
            a.template_action(1, "QueueConstruction")
        except Exception:
            pass
        return a.ship_construction_move(0, 0)
    if recv == "MilitaryFormation":
        if cmd == "GetDisbandUnitTypeConscriptCommand":
            return a.unit_entry_action(0, 0, "DisbandConscript")
        if cmd == "GetUpgradeConscriptUnitTypeCommand":
            return a.unit_entry_action(0, 0, "UpgradeConscript")
        if cmd == "GetUpgradeRegularUnitTypeCommand":
            return a.unit_entry_action(0, 0, "UpgradeRegular")
        if cmd == "GetUpgradeUnitGroupCommand":
            return a.unit_group_action(0, 0)
        if cmd == "CreateNavalMissionWithPreviousArea":
            return a.naval_mission_action(0, 0, cmd=cmd)
        if cmd == "Disband":
            return a.formation_action(4, "Disband")
        fleets = cmd in ("RetrofitShips", "RetrofitShipsAndStation", "CancelRetrofitShips",
                         "RecallForRepairs", "RemoveNavalMission")
        return a.formation_action(0, cmd, fleets=fleets)
    if recv in ("MilitaryFormationWrapped", "TransportPlannerPopup"):
        return _embark(a)
    if recv == "Front":
        return a.front_action(0, cmd)
    if recv == "Hq":
        return a.hq_action(0, cmd)
    if recv == "Invasion":
        return a.invasion_action(0, 0, cmd, formation=0)
    if recv == "Proposal":
        return a.answer_proposal(0, accept="Accept" in cmd)
    if recv == "Country":
        if cmd == "Kick":
            return a.kick_from_bloc("汉诺威")
        if cmd == "ToggleIgnoreDecision":
            return a.toggle_ignore_decision("宣告英属印度成立")
        if cmd == "ToggleIgnoreCountryFormation":
            return a.toggle_ignore_formation("大哥伦比亚")
    if recv == "CountryFormation":
        return a.support_candidate("德国", 0)
    if recv == "Building":
        return a.queue_military_construction(5, "building_shipyard", 0, "infantry")
    if recv == "BuildingType":
        return a.building_type_action("building_shipyard", cmd)
    if recv == "BuildingBrowserBuildingTypeItem":
        m = {"ToggleAllSubsidies": "Subsidies", "ToggleAllAutoExpand": "AutoExpand",
             "ToggleAllPrivatization": "Privatization", "RemoveAllPrivatization": "RemoveAllPrivatization"}
        return a.building_type_toggle_all("building_shipyard", m[cmd])
    if recv == "DecommissionSupplyShipsWindow":
        return a.decommission_supply_ships(1)
    if recv == "DiplomaticAction":
        return a.diplomatic_action("FRA", "increase_relations")
    if recv == "DiplomaticPlay":
        return a.play_stance(0, cmd)
    if recv == "DiplomaticPlayConfirmation":
        return a.start_play("dp_humiliation", "TUS")
    if recv == "PowerBlocPrinciple":
        return a.upgrade_principle(0)
    if recv == "PowerBlocFormation":
        return a.power_bloc_formation()
    if recv == "ShipDesignerPopup":
        return a.ship_designer_create(edit="Edit" in cmd)
    if recv == "SwayCountryPanel":
        return a.create_sway(0, "FRA")
    if recv == "TransferFormationPopup":
        return a.transfer_formation(0, 1)
    if recv == "PrestigeGoodChangeNamePopup":
        return a.rename_prestige_good("company_hbc", 0, "MCP奢侈")
    if recv == "TechTreeLine":
        return a.research("urban_planning")
    if recv == "WarGoal":
        return a.war_goal(0, cmd)
    if recv == "WarPanel":
        return a.peace(0, "SetWhitePeace")
    raise ValueError(f"没有测试分发：{key}")


def main() -> int:
    rows = json.load(open(os.path.join(ROOT, "src", "agent", "data", "actions.json"), encoding="utf-8"))
    wired = [r for r in rows if r["status"] == "已接"]
    from agent import server
    a = Coverage(server.bridge)
    try:
        a.template_action(0, "QueueConstruction")
    except Exception:
        pass
    if not a.plays():
        try:
            a.start_play("dp_humiliation", "NET")
        except Exception:
            pass
    out = []
    for r in wired:
        key = f"{r['receiver']}.{r['command']}"
        try:
            res = _norm(run_key(a, key))
            res["key"] = key
        except (GameError, ValueError) as e:
            res = {"key": key, "ok": False, "detail": f"{type(e).__name__}: {e}"}
            print("BLC", key, res["detail"][:120])
        except Exception as e:
            res = {"key": key, "ok": False, "error": f"{type(e).__name__}: {e}",
                   "trace": traceback.format_exc(limit=2)}
            print("ERR", key, res["error"])
        out.append(res)
        mark = "OK " if res.get("ok") else "...."
        detail = res.get("detail") or res.get("error") or str(res.get("result", ""))[:60]
        print(f"{mark} {key}  {str(detail)[:110]}")
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    ok = sum(1 for x in out if x.get("ok"))
    err = sum(1 for x in out if x.get("error"))
    print(f"\nwired {len(out)}：ok {ok}，不可用 {len(out)-ok-err}，测试异常 {err}\n{OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
