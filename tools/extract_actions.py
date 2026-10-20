"""从游戏界面文件抽取全部玩家命令 → src/agent/data/actions.json + docs/actions.md

玩家在界面上能做的每个操作，最终都是一条数据系统命令：按钮的 onclick 里写成
Execute(X) / AskConfirmation(X) / AskConfirmationCustom(X, ...) / ExecuteOrAskConfirmationIfNeeded(X) 等，
X 是返回游戏命令的表达式（如 Law.StartEnacting、Building.QueueConstruction）。按钮的可用判断 IsValid(X) 里的 X 也收：
有的命令只在 IsValid 里出现（研究按钮发的是 ResearchWithUnlocks，Technology.Research 只用来判断）。
剧本界面按钮 GetScriptedGui('名字').Execute(...) 单独记为 ScriptedGui.名字（debug_ 开头的不收）。
把这些 X 全部提出来，就是「玩家能做的操作」的分母；桥接层用同样的 Execute(X) 执行。

不收：ExecuteConsoleCommand（开发者控制台）、frontend / tools / settings 等主菜单与调试界面。
每条命令按「接收对象」分类，标出从玩家国家能否直接走到（能走到的照现有做法即可；
挂在窗口上的要像改组政府那样构造对象；地图 / 军事类要组合多个对象），以及是否已验证。

用法：
    python tools/extract_actions.py            # 游戏目录自动找，或设 V3MCP_GAME_DIR
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

from agent import paths  # noqa: E402

OUT_JSON = os.path.join(ROOT, "src", "agent", "data", "actions.json")
OUT_MD = os.path.join(ROOT, "docs", "actions.md")

# 这些包装函数的第一个参数是游戏命令
WRAPPERS = ("Execute", "AskConfirmation", "AskConfirmationWithSound", "AskConfirmationCustom",
            "ExecuteOrAskConfirmationIfNeeded", "IsValid")
SKIP_DIRS = {"frontend", "tools", "settings", "pdx_account", "achievements"}

# 已在真实游戏里跑通、有前后核实的命令（接收对象.函数）→ 对应的 Actions 方法
VERIFIED = {
    "Country.SetTaxLevelVeryLow": "Actions.set_tax",
    "Country.SetTaxLevelLow": "Actions.set_tax",
    "Country.SetTaxLevelMedium": "Actions.set_tax",
    "Country.SetTaxLevelHigh": "Actions.set_tax",
    "Country.SetTaxLevelVeryHigh": "Actions.set_tax",
    "Technology.Research": "Actions.research",
    "Law.StartEnacting": "Actions.enact_law",
    "Building.QueueConstruction": "Actions.build",
    "ProductionMethod.GetSwitch": "Actions.set_pm",
    "ReformGovernment.Confirm": "Actions.reform_government",
    "Goods.ToggleTaxation": "Actions.toggle_consumption_tax",
    "Country.CreateCompany": "Actions.company",
    "Country.RemoveCompany": "Actions.company",
    "EventOption.Select": "Actions.choose_event_option",
    "Country.StartNegotiationWith": "Actions.negotiate",
    "Decision.TakeDecision": "Actions.take_decision",
    "ScriptedButton.ExecuteEffect": "Actions.press_button",
    "Institution.StartChangingLevelTo": "Actions.set_institution",
    "Institution.StopSizeChange": "Actions.stop_institution_change",
    "PoliticalMovement.ToggleBolstering": "Actions.toggle_movement",
    "PoliticalMovement.ToggleSuppression": "Actions.toggle_movement",
    "Law.StopEnacting": "Actions.stop_enacting",
    "Law.StartImposing": "Actions.impose_law",
    "Amendment.Repeal": "Actions.repeal_amendment",
    **{f"ConstructionQueueElement.Move{h}": "Actions.move_construction" for h in ("Up", "Down", "ToTop", "ToBottom")},
    "ConstructionQueueElement.CancelConstruction": "Actions.cancel_construction",
    **{f"Building.{c}": "Actions.building_action" for c in (
        "CancelConstruction", "Downsize", "NationalizeBuildingLevels", "PauseConstructionOutput",
        "ResumeConstructionOutput", "ToggleAutoExpand", "ToggleAutoExpandOn", "ToggleAutoExpandOff",
        "TogglePrivatization", "ToggleSubsidies", "ToggleSubsidiesOn", "ToggleSubsidiesOff",
        "ResetProductionMethodsToStandard")},
    "BuildingType.ResetProductionMethodsToStandard": "Actions.building_action",
    "Global.ChangeAllConstructionSpeed": "Actions.construction_speed",
    "Global.PauseAllConstruction": "Actions.construction_speed",
    "Global.ResumeAllConstruction": "Actions.construction_speed",
    "DecreeType.GetSetCommand": "Actions.set_decree",
    "Decree.GetRemoveCommand": "Actions.remove_decree",
    "State.IncorporateState": "Actions.state_action",
    "State.UnincorporateState": "Actions.state_action",
    "State.TogglePauseColonization": "Actions.state_action",
    "State.AbandonColony": "Actions.state_action",
    "State.Colonize": "Actions.colonize",
    "Company.ToggleCharter": "Actions.toggle_charter",
    "Company.ToggleBuildingCharter": "Actions.target_charter",
    "Company.ToggleRegionCharter": "Actions.target_charter",
    "Technology.ResearchWithUnlocks": "Actions.queue_research",
    "Technology.AddToQueueWithUnlocks": "Actions.queue_research",
    "Technology.RemoveFromQueue": "Actions.queue_research",
    "Country.MobilizeAllArmies": "Actions.country_command",
    "Country.DemobilizeAllArmies": "Actions.country_command",
    "DiplomaticAction.ExecuteWithConfirmation": "Actions.diplomatic_action",
    "DiplomaticActionWindow.ExecuteAction": "Actions.diplomatic_action",
    "DiplomaticPlayType.GetStartCommandCountry": "Actions.start_play",
    "WarGoal.ToggleIsPressedInPotentialPeaceDeal": "Actions.war_goal",
    "War.ToggleAcceptPeace": "Actions.accept_peace",
    "WarPanel.ProposePeaceDeal": "Actions.peace",
    "Treaty.WithdrawFromTreaty": "Actions.withdraw_treaty",
    "DiplomaticPlayType.GetStartCommandState": "Actions.start_play",
    "Character.GetRecruitCommandNoFormation": "Actions.recruit_commander",
    "Character.RecruitCharacterNoFormation": "Actions.recruit_commander",
    "Character.GetRecruitCommand": "Actions.recruit_commander",
    "Character.GetPromoteCommand": "Actions.commander_action",
    "Character.UnassignFromFormation": "Actions.commander_action",
    "Character.AssignToFormation": "Actions.commander_action",
    "Character.SelectOrder": "Actions.commander_action",
    "Country.SetDefaultConstructionFleet": "Actions.default_construction_fleet",
    "Country.ClearDefaultConstructionFleet": "Actions.default_construction_fleet",
    "CountryFormation.FormCountry": "Actions.form_country",
    "PowerBloc.Kick": "Actions.kick_from_bloc",
    "PowerBlocPrinciple.UpgradeToNextLevel": "Actions.upgrade_principle",
    "Country.LeavePowerBloc": "Actions.country_command",
    "Country.DeclareBankruptcy": "Actions.country_command",
    "WarPanel.Capitulate": "Actions.peace",
    "DiplomaticPlay.Yield": "Actions.play_stance",
    **{f"DiplomaticPlay.{s}": "Actions.play_stance" for s in (
        "DeclareNeutrality", "BeOnTheFence", "LeanTowardsInitiator", "LeanTowardsTarget",
        "SupportInitiator", "SupportTarget")},
    **{f"Country.{c}": "Actions.country_command" for c in (
        "PauseConstruction", "ResumeConstruction", "PauseShipConstruction", "ResumeShipConstruction")},
    **{f"Country.Set{k}{t}": via for k, via in (("GovernmentWageLevel", "Actions.set_wage"),
                                                ("MilitaryWageLevel", "Actions.set_wage"),
                                                ("SupplyShipConstructionLevel", "Actions.set_supply_ships"))
       for t in ("VeryLow", "Low", "Medium", "High", "VeryHigh")},
    # 关税 / 补贴：直接在玩家国家上（Country.*），以及预算面板按商品走到市场所有者的写法（Goods.*，经 Actions.command）
    **{f"{r}.Set{side}{p}": via for r, via in (("Country", "Actions.set_trade_policy"), ("Goods", "Actions.command"))
       for side in ("Import", "Export")
       for p in ("TariffsNone", "TariffsLow", "TariffsHigh", "TariffsMax",
                 "SubventionsLow", "SubventionsHigh", "SubventionsMax")},
}

# 接收对象 → (领域, 可达性)。可达性：
#   直达 —— 从玩家国家沿列表能走到（国家、州、建筑、法律、人物……），照现有做法：找路径、IsValid、Execute、核实
#   窗口 —— 对象只存在于某个界面窗口 / 弹窗 / 草稿里，要像改组政府那样逆向它读的字段再自己构造
#   组合 —— 军事 / 地图类：目标能从数据里找到，但要组合编队、前线、海域等多个对象
#   界面 —— 只影响界面本身（选中、改名、显示），对游戏局面没有作用
RECEIVERS = {
    "Country": ("国家", "直达"), "Law": ("政治", "直达"),
    "InterestGroup": ("政治", "直达"), "PoliticalMovement": ("政治", "直达"), "Party": ("政治", "直达"),
    "Character": ("人物", "直达"), "Institution": ("政治", "直达"), "ReformGovernment": ("政治", "窗口"),
    "Technology": ("研究", "直达"), "Building": ("经济", "直达"), "BuildingType": ("经济", "直达"),
    "State": ("经济", "直达"), "ProductionMethod": ("经济", "直达"),
    "ConstructionQueueElement": ("经济", "直达"), "Company": ("经济", "直达"), "Market": ("经济", "直达"),
    "Goods": ("经济", "直达"), "TradeRoute": ("经济", "直达"), "BuildingBrowserBuildingTypeItem": ("经济", "窗口"),
    "JournalEntry": ("日志", "直达"), "ScriptedButton": ("日志", "直达"), "Decision": ("日志", "直达"),
    "Event": ("事件", "窗口"), "EventOption": ("事件", "窗口"), "EventWindow": ("事件", "窗口"),
    "DiplomaticAction": ("外交", "直达"), "DiplomaticPact": ("外交", "直达"), "DiplomaticPlay": ("外交", "直达"),
    "DiplomaticDemand": ("外交", "直达"), "Proposal": ("外交", "直达"), "Treaty": ("外交", "直达"),
    "TreatyDraft": ("外交", "窗口"), "WarGoal": ("外交", "直达"), "WarGoalDraft": ("外交", "窗口"),
    "SwayCountryPanel": ("外交", "窗口"), "PowerBloc": ("外交", "直达"),
    "PowerBlocPrincipleSelectionWindow": ("外交", "窗口"), "CountryFormation": ("外交", "直达"),
    "ReleaseCountryWindow": ("外交", "窗口"), "War": ("军事", "直达"), "WarPanel": ("军事", "窗口"),
    "MilitaryFormation": ("军事", "组合"), "Front": ("军事", "组合"), "Strait": ("军事", "组合"),
    "Invasion": ("军事", "组合"), "Ship": ("军事", "组合"), "ShipTemplate": ("军事", "组合"),
    "ShipConstruction": ("军事", "组合"), "ShipSelection": ("军事", "组合"), "SeaNodeMovementMarker": ("军事", "组合"),
    "MobilizationOption": ("军事", "组合"), "TransportPlannerPopup": ("军事", "窗口"),
    "TransferFormationPopup": ("军事", "窗口"), "ShipDesignerPopup": ("军事", "窗口"),
    "RulerSelectionPopup": ("人物", "窗口"),
    "Amendment": ("政治", "直达"), "Decree": ("经济", "直达"), "DecreeType": ("经济", "直达"),
    "DiplomaticPlayConfirmation": ("外交", "窗口"), "PowerBlocFormation": ("外交", "窗口"),
    "AddWarGoalPanel": ("外交", "窗口"), "DiplomaticActionWindow": ("外交", "窗口"),
    "CombatUnit": ("军事", "组合"), "Hq": ("军事", "组合"), "MilitaryFormationWrapped": ("军事", "组合"),
    "MilitaryFormationBorrowSetting": ("军事", "组合"), "PanelMilitary": ("军事", "窗口"),
    "GetDraggedDatacontext": ("军事", "界面"), "DecommissionSupplyShipsWindow": ("军事", "窗口"),
    "InvasionPlannerPopup": ("军事", "窗口"), "ScriptedGui": ("日志", "直达"),
    "DiplomaticPlayType": ("外交", "直达"), "PowerBlocPrinciple": ("外交", "直达"), "TechTreeLine": ("研究", "窗口"),
}
# 不经 Execute、直接写在 onclick 里的真操作（其余直接调用都是排序、置顶、缩放地图、草稿窗口里填参数）
DIRECT_ONCLICK = {
    "EventOption.Select": ("事件", "窗口"),
    "DiplomaticAction.ExecuteWithConfirmation": ("外交", "直达"),
    "Character.RecruitCharacterNoFormation": ("人物", "直达"),
}
_ONCLICK = re.compile(r'onclick\s*=\s*"\[(' + "|".join(re.escape(k) for k in DIRECT_ONCLICK) + r")\b")
SKIP_RECEIVERS = {"GuiScope"}   # 调试用剧本界面的参数

# 全局命令（不带接收对象）：建造类直接可用；「选中的编队 / 舰队」类依赖界面上的选择，归为组合
GLOBAL_ECONOMY = ("ChangeAllConstructionSpeed", "PauseAllConstruction", "ResumeAllConstruction")
# 只影响界面的：改名、在列表里隐藏、置顶。注意 Toggle* 多是真操作（补贴、私有化、公司特许、暂停殖民）
COSMETIC = re.compile(r"(ChangeName|SetName|Rename|NamePopup|ToggleIgnore|Pin)", re.I)

# 前面可以有 PopupManager. 之类；但「xxx.Execute(」是剧本界面的 Execute，另行处理（scan 里跳过）
_WRAP = re.compile(r"(?<!\w)(" + "|".join(WRAPPERS) + r")\s*\(")
_SCRIPTED_GUI = re.compile(r"GetScriptedGui\('(\w+)'\)\.Execute\(")


def first_arg(text: str, start: int) -> str:
    """text[start] 紧跟在 "(" 之后：取到同层第一个逗号或右括号为止。"""
    depth = 0
    i = start
    while i < len(text):
        c = text[i]
        if c in "([":
            depth += 1
        elif c in ")]":
            if depth == 0:
                break
            depth -= 1
        elif c == "," and depth == 0:
            break
        elif c in "\"\n":
            break
        i += 1
    return re.sub(r"\s+", "", text[start:i])


def split_top(expr: str) -> list[str]:
    """按顶层的点切分：GetPlayer.AccessRuler.Kill(x.y) → [GetPlayer, AccessRuler, Kill(x.y)]"""
    parts, depth, cur = [], 0, ""
    for c in expr:
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        if c == "." and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += c
    parts.append(cur)
    return parts


def command_key(expr: str) -> tuple[str, str] | None:
    """(接收对象, 命令函数)。接收对象取表达式的第一段（GetPlayer 归为 Country）。"""
    parts = [p for p in split_top(expr) if p]
    if not parts or not re.match(r"[A-Za-z]", parts[0]):
        return None
    if len(parts) == 1:                       # 全局命令：ChangeAllConstructionSpeed(ProductionMethod.Self)
        return "Global", parts[0].split("(")[0]
    receiver = parts[0].split("(")[0]
    if receiver in ("GetPlayer", "AccessPlayer", "GetMetaPlayer"):
        receiver = "Country"
    func = parts[-1].split("(")[0]
    return receiver, func


def scan(gui_dir: str) -> dict[str, dict]:
    found: dict[str, dict] = {}
    for dirpath, dirs, files in os.walk(gui_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if not name.endswith(".gui"):
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, gui_dir).replace("\\", "/")
            text = open(path, encoding="utf-8-sig", errors="replace").read()
            hits = [(m.group(1), first_arg(text, m.end())) for m in _WRAP.finditer(text)
                    if not (m.group(1) == "Execute" and text[m.start() - 1] == ".")]
            hits += [("ScriptedGui", f"ScriptedGui.{m.group(1)}") for m in _SCRIPTED_GUI.finditer(text)
                     if not m.group(1).startswith("debug_")]
            hits += [("onclick", m.group(1)) for m in _ONCLICK.finditer(text)]
            for wrapper, expr in hits:
                key = command_key(expr) if expr else None
                if not key or key[0] in SKIP_RECEIVERS:
                    continue
                k = ".".join(key)
                row = found.setdefault(k, {"receiver": key[0], "command": key[1], "examples": [], "files": set(),
                                           "confirm": False, "count": 0})
                row["count"] += 1
                row["files"].add(rel)
                row["confirm"] |= wrapper.startswith(("Ask", "ExecuteOr"))
                row["executed"] = row.get("executed", False) or wrapper != "IsValid"
                if expr not in row["examples"] and len(row["examples"]) < 3:
                    row["examples"].append(expr)
    return found


_LEVEL = re.compile(r"(VeryLow|VeryHigh|Low|Medium|High|Max|None|On|Off)$")


def family(row: dict) -> str:
    """操作种类：只差档位的算一种（SetTaxLevelLow / High … → SetTaxLevel*）；
    关税等经商品走到国家的写法与直接在国家上的算同一种。"""
    receiver = "Country" if row["receiver"] == "Goods" and row["command"].startswith(("SetImport", "SetExport")) \
        else row["receiver"]
    cmd = _LEVEL.sub("*", row["command"]) if _LEVEL.search(row["command"]) and row["command"].startswith("Set") \
        else row["command"]
    return f"{receiver}.{cmd}"


def classify(row: dict) -> None:
    k = f"{row['receiver']}.{row['command']}"
    domain, reach = DIRECT_ONCLICK.get(k) or RECEIVERS.get(row["receiver"], ("其他", "待查"))
    if row["receiver"] == "Global":
        domain, reach = ("经济", "直达") if row["command"] in GLOBAL_ECONOMY else ("军事", "组合")
    if row["receiver"].endswith(("Popup", "Window", "Panel", "Draft")) and reach == "待查":
        reach = "窗口"
    if COSMETIC.search(row["command"]) or "ChangeNamePopup" in row["receiver"]:
        reach = "界面"
    row["domain"] = domain
    row["reach"] = reach
    row["family"] = family(row)
    row["status"] = "已验证" if k in VERIFIED else "未做"
    row["via"] = VERIFIED.get(k, "")


ORDER = ["国家", "经济", "政治", "研究", "人物", "日志", "事件", "外交", "军事", "其他"]
REACH_ORDER = ["直达", "窗口", "组合", "待查", "界面"]


def render(rows: list[dict]) -> str:
    total = len(rows)
    done = sum(r["status"] == "已验证" for r in rows)
    fams: dict[str, dict] = {}
    for r in rows:
        f = fams.setdefault(r["family"], {"reach": r["reach"], "done": False})
        f["done"] |= r["status"] == "已验证"
    by_reach: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for f in fams.values():
        by_reach[f["reach"]][0] += 1
        by_reach[f["reach"]][1] += f["done"]
    lines = [
        "# 玩家操作清单",
        "",
        "由 `tools/extract_actions.py` 从游戏界面文件（`game/gui/**/*.gui`）自动生成，机器可读版在",
        "`src/agent/data/actions.json`。每一行是界面按钮背后的一条游戏命令"
        "（`Execute(X)`、`AskConfirmation(X)` 等的参数 X），桥接层用同样的 `Execute(X)` 执行。",
        "",
        "可达性：**直达** = 从玩家国家沿列表能走到对象，照现有做法即可；**窗口** = 对象只存在于界面窗口 / 弹窗 / 草稿里，"
        "要像改组政府那样构造（见 docs/bridge.md）；**组合** = 军事 / 地图类，要组合编队、前线、海域等多个对象；"
        "**界面** = 只影响界面显示（改名、开关、定位），不影响局面；**待查** = 接收对象还没归类。",
        "",
        f"**进度：命令 {done} / {total} 已验证；按操作种类（只差档位的算一种）"
        f"{sum(f['done'] for f in fams.values())} / {len(fams)}。**",
        "",
        "按可达性（操作种类，已验证 / 总数）：" +
        "，".join(f"{k} {by_reach[k][1]} / {by_reach[k][0]}" for k in REACH_ORDER if k in by_reach) + "。",
        "",
        "不在本表、但同样要打通的：立即存档（目前用自动存档）、"
        "暂停 / 调速（`TimeKeeper`，已验证，不经 Execute）。事件选项在「事件」一节（`EventOption.Select`）。"
        "每条命令用的路径与核实方式见 docs/bridge.md「已验证的玩家动作」。",
        "",
    ]
    for domain in ORDER:
        group = [r for r in rows if r["domain"] == domain]
        if not group:
            continue
        group.sort(key=lambda r: (r["status"] != "已验证", REACH_ORDER.index(r["reach"]), r["receiver"], r["command"]))
        lines += [f"## {domain}（{sum(r['status'] == '已验证' for r in group)} / {len(group)}）", "",
                  "| 状态 | 可达性 | 命令 | 例子 | 界面文件 |", "|---|---|---|---|---|"]
        for r in group:
            mark = f"✓ `{r['via']}`" if r["status"] == "已验证" else ""
            ex = r["examples"][0].replace("|", "\\|")
            files = (", ".join(r["files"][:2]) + (" …" if len(r["files"]) > 2 else "")) if r["files"] else "（程序生成的菜单）"
            lines.append(f"| {mark} | {r['reach']} | `{r['receiver']}.{r['command']}` | `{ex}` | {files} |")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    gui = os.path.join(paths.game_dir(), "game", "gui")
    found = scan(gui)
    for k in VERIFIED:          # 界面文件里没直接出现的（生产方式切换菜单由程序生成）也列上
        if k not in found:
            receiver, command = k.split(".", 1)
            found[k] = {"receiver": receiver, "command": command, "examples": [k], "files": [],
                        "confirm": False, "count": 0, "executed": True}
    rows = []
    for _, row in sorted(found.items()):
        row["files"] = sorted(row["files"])
        classify(row)
        rows.append(row)
    with open(OUT_JSON, "w", encoding="utf-8", newline="\n") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
        f.write("\n")
    with open(OUT_MD, "w", encoding="utf-8", newline="\n") as f:
        f.write(render(rows) + "\n")
    done = sum(r["status"] == "已验证" for r in rows)
    print(f"{len(rows)} 条命令（{len({r['family'] for r in rows})} 种操作），已验证 {done}；待查接收对象：",
          sorted({r["receiver"] for r in rows if r["reach"] == "待查"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
