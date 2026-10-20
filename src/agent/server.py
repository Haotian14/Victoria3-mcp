"""MCP 入口。策略全部在代码里（strategy/），这里只暴露薄工具：

- play / step / advise     自动玩若干个月 / 只走一个月的决策 / 只看计划不执行
- get_state / act / query  实时局面、手动下发一个动作、求任意界面表达式
- launch_game / health     启动游戏（不经启动器、注入桥接层）/ 桥接层是否在线
- search / lookup / rank_buildings / building_economics   查游戏定义、算建筑经济账
- country_state / save_summary                             解析存档（兜底，慢）

运行：python -m agent.server（工作目录 src/），或见仓库根目录的 .mcp.json。
"""

from __future__ import annotations

import os
import sys
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "agent"

from mcp.server.mcpserver import MCPServer  # noqa: E402

from agent import gamedata, observe, paths, pdx, runner, save, state  # noqa: E402
from agent.actions import Actions  # noqa: E402
from agent.bridge import Bridge, BridgeError, GameError, plain  # noqa: E402
from agent.game import Clock, launch, wait_in_game  # noqa: E402
from agent.strategy import economy  # noqa: E402

bridge = Bridge()

# act 里参数放在 params 的动作：Actions 方法名 → 参数说明
ACT_PARAMS = {
    "command": "cmd, probe, path=[[列表, 下标]...], target, probe_path",
    "set_wage": "which: Government/Military, level",
    "set_supply_ships": "level",
    "set_trade_policy": "goods, side: Import/Export, policy: TariffsNone/TariffsLow/TariffsHigh/TariffsMax/"
                        "SubventionsLow/SubventionsHigh/SubventionsMax",
    "toggle_consumption_tax": "goods",
    "country_command": "cmd: MobilizeAllArmies/DemobilizeAllArmies/PauseConstruction/ResumeConstruction/"
                       "PauseShipConstruction/ResumeShipConstruction/DeclareBankruptcy/LeavePowerBloc",
    "company": "key: 公司类型, create: true 创建 / false 解散",
    "negotiate": "ig_index: 利益集团下标",
    "choose_event_option": "event_id, option（events 工具列出的序号）",
    "press_button": "entry: 日志条目 key, button: 按钮名字（journal 工具列出）",
    "take_decision": "decision: 决议名字（journal 工具列出）",
    "set_institution": "institution: 机构名字, level",
    "stop_institution_change": "institution",
    "toggle_movement": "movement: 运动名字, action: Bolstering/Suppression",
    "stop_enacting": "（无参数）取消正在推行的法律",
    "impose_law": "subject: 附属国名字, law: 法律名字",
    "repeal_amendment": "amendment: 修正案名字",
    "move_construction": "index（construction_queue 里的序号）, how: Up/Down/ToTop/ToBottom, private=false",
    "cancel_construction": "index, private=false",
    "building_action": "state: 州 id 或州名, building: building_* 键, cmd: ToggleSubsidies/ToggleSubsidiesOn/"
                       "ToggleSubsidiesOff/ToggleAutoExpand(On/Off)/TogglePrivatization/Nationalize(levels)/Downsize/"
                       "CancelConstruction/PauseConstructionOutput/ResumeConstructionOutput/"
                       "ResetProductionMethodsToStandard/GetBuildingType.ResetProductionMethodsToStandard",
    "construction_speed": "pm: 建造部门生产方式（全部换成它），或 pause: true/false（暂停 / 恢复全部建造）",
    "set_decree": "state, decree: 法令中文名",
    "remove_decree": "state, decree",
    "state_action": "state, cmd: IncorporateState/UnincorporateState/TogglePauseColonization/AbandonColony",
    "colonize": "region: STATE_* 键",
    "toggle_charter": "company: 公司类型 key, charter: 特许状中文名（如 贸易权）",
    "target_charter": "company, charter: industry_charter/monopoly_charter/colonization_charter, "
                      "building: building_* 或 region: STATE_*（再执行一次是撤销）",
}

server = MCPServer(
    name="victoria3",
    instructions=(
        "《维多利亚 3》单机辅助。当前为第一阶段：只读 —— 查游戏定义、算建筑经济账、读文本存档。\n"
        "id 一律是游戏内部 id（building_food_industry、pm_bakery、grain）；不知道 id 先用 search。\n"
        "仅用于单机游玩，不得用于多人模式。"
    ),
)


def _econ_dict(gd: gamedata.GameData, e: economy.BuildingEconomics) -> dict[str, Any]:
    return {
        "building": e.building,
        "name": gd.name("buildings", e.building),
        "construction": e.construction,
        "value_added": round(e.value_added, 1),
        "per_construction": round(e.per_construction, 3) if e.per_construction else None,
        "workers": e.workers,
        "per_worker": round(e.per_worker, 4) if e.per_worker else None,
        "inputs": e.inputs,
        "outputs": e.outputs,
        "pms": [{"pmg": c.pmg, "pm": c.pm, "name": gd.name("production_methods", c.pm),
                 "value_added": round(c.value_added, 1)} for c in e.choices],
    }


@server.tool(description="按 id 或中英文名模糊查找游戏定义（商品、建筑、生产方式、科技、法律）。")
def search(text: str, limit: int = 20) -> list[dict[str, str]]:
    return gamedata.get().search(text, limit)


@server.tool(description=(
    "读取一条游戏定义。kind 取 goods / buildings / production_methods / "
    "production_method_groups / technologies / laws / law_groups。"
))
def lookup(kind: str, id: str) -> dict[str, Any]:
    gd = gamedata.get()
    if kind not in gamedata.TABLES:
        return {"ok": False, "error": f"未知的 kind：{kind}", "kinds": list(gamedata.TABLES)}
    row = gd.table(kind).get(id)
    if row is None:
        return {"ok": False, "error": f"{kind} 里没有 {id}", "similar": gd.search(id, 5)}
    return {"ok": True, "kind": kind, "id": id, **row}


@server.tool(description=(
    "可建造建筑按「每点建造力的每周增加值」排序（产出 − 投入，按商品价格；不含工资）。"
    "from_save=true 时用最新存档里玩家国家的本地价格、已研究科技、现行法律（解析约 15 秒，之后缓存）。"
    "否则：techs 给定时只看已解锁的（自动补前置）；laws 给定时按法律过滤生产方式。"
    "prices 覆盖商品价格（默认基准价）。尚未检查各州是否有对应资源。"
))
def rank_buildings(from_save: bool = False, techs: list[str] | None = None,
                   laws: list[str] | None = None, prices: dict[str, float] | None = None,
                   limit: int = 20) -> list[dict[str, Any]] | dict[str, Any]:
    gd = gamedata.get()
    if from_save:
        cs = _player_state()
        if isinstance(cs, dict):
            return cs
        tech_set, law_set = cs.techs, cs.laws
        merged = {**gd.base_prices(), **cs.prices, **(prices or {})}
    else:
        tech_set = gd.tech_closure(set(techs)) if techs is not None else None
        law_set = set(laws) if laws is not None else None
        merged = {**gd.base_prices(), **(prices or {})}
    return [_econ_dict(gd, e) for e in economy.rank_buildings(gd, merged, tech_set, law_set, limit)]


@server.tool(description="单个建筑的经济账：逐个生产方式组挑增加值最高的已解锁生产方式。参数同 rank_buildings。")
def building_economics(building: str, techs: list[str] | None = None, laws: list[str] | None = None,
                       prices: dict[str, float] | None = None) -> dict[str, Any]:
    gd = gamedata.get()
    if building not in gd.buildings:
        return {"ok": False, "error": f"没有建筑 {building}", "similar": gd.search(building, 5)}
    tech_set = gd.tech_closure(set(techs)) if techs is not None else None
    law_set = set(laws) if laws is not None else None
    merged = {**gd.base_prices(), **(prices or {})}
    return {"ok": True, **_econ_dict(gd, economy.building_economics(gd, building, merged, tech_set, law_set))}


@server.tool(description=(
    "读存档并列出顶层结构（每个键的类型与大小）。path 为空时读存档目录里最新的 .v3。"
    "只支持文本存档：用 -debug_mode 启动游戏后保存的存档。大存档可能要一分钟以上。"
))
def save_summary(path: str = "") -> dict[str, Any]:
    path = path or paths.latest_save() or ""
    if not path:
        return {"ok": False, "error": f"存档目录里没有 .v3：{paths.save_dir()}"}
    try:
        raw = save.read_raw(path)
        state = pdx.to_obj(pdx.parse(raw.gamestate))
    except (OSError, save.SaveFormatError, pdx.ParseError) as e:
        return {"ok": False, "path": path, "error": str(e)}
    if not isinstance(state, dict):
        return {"ok": False, "path": path, "error": "gamestate 顶层不是键值块"}
    keys = {k: _shape(v) for k, v in state.items()}
    return {"ok": True, "path": path, "header": raw.header, "date": state.get("date"), "keys": keys}


def _player_state(path: str = "") -> state.CountryState | dict[str, Any]:
    path = path or paths.latest_save() or ""
    if not path:
        return {"ok": False, "error": f"存档目录里没有 .v3：{paths.save_dir()}"}
    try:
        return state.extract(state.load_gamestate(path), gamedata.get())
    except (OSError, save.SaveFormatError, pdx.ParseError, KeyError, ValueError) as e:
        return {"ok": False, "path": path, "error": f"{type(e).__name__}: {e}"}


@server.tool(description=(
    "玩家国家的当前局面（读最新或指定存档）：国库、收支、税率、本地与世界市场价格（与基准价对比）、"
    "已研究科技、现行法律，以及各州建筑（等级、生产方式、雇佣、利润）。"
    "解析约 15 秒，存档未变时走缓存。"
))
def country_state(path: str = "", states_limit: int = 12) -> dict[str, Any]:
    cs = _player_state(path)
    if isinstance(cs, dict):
        return cs
    gd = gamedata.get()
    base = gd.base_prices()
    prices = {g: {"name": gd.name("goods", g), "local": round(p, 2),
                  "world": round(cs.world_prices[g], 2) if g in cs.world_prices else None,
                  "base": base.get(g)}
              for g, p in sorted(cs.prices.items())}
    states_out = []
    for s in sorted(cs.states, key=lambda s: -sum(b.levels for b in s.buildings))[:states_limit]:
        states_out.append({
            "id": s.id, "region": s.region, "arable_land": s.arable_land,
            "infrastructure": s.infrastructure, "infrastructure_usage": s.infrastructure_usage,
            "buildings": [{"building": b.building, "name": gd.name("buildings", b.building),
                           "levels": b.levels, "pms": b.pms, "staffing": b.staffing,
                           "profit": round(b.profit, 1) if b.profit is not None else None}
                          for b in sorted(s.buildings, key=lambda b: -b.levels)],
        })
    return {
        "ok": True, "date": cs.date, "country_id": cs.country_id, "tag": cs.tag, "name": cs.name,
        "government": cs.government, "tax_level": cs.tax_level,
        "money": cs.money, "credit": cs.credit,
        "weekly_income": round(cs.weekly_income, 1), "weekly_expense": round(cs.weekly_expense, 1),
        "base_wage": cs.base_wage,
        "techs": sorted(cs.techs),
        "laws": [{"law": law, "name": gd.name("laws", law),
                  "group": (gd.laws.get(law) or {}).get("group")} for law in sorted(cs.laws)],
        "prices": prices,
        "states": states_out,
    }


# ------------------------------------------------------------------ 游玩（经桥接层）

@server.tool(description=(
    "按策略自动玩 months 个月（每月：读局面 → 决策 → 执行并逐条核实 → 推进到下月 1 日）。"
    "save 不为空时先重启游戏并载入该存档；tag 不为空时用控制台换成该国（如 PRU）。"
    "baseline=true 时不做任何动作，只记录指标（对照组）。结果追加到 logs/runs.jsonl。"
))
def play(months: int = 12, save: str = "", tag: str = "", baseline: bool = False) -> dict[str, Any]:
    if save:
        launch(save=save, restart=True, autosave="yearly")
    wait_in_game(bridge)
    Clock(bridge).pause()
    if tag:
        bridge.console(f"tag {tag}")
    label = ("baseline" if baseline else "strategy") + (f":{tag}" if tag else "")
    s = runner.play(bridge, months, label=label, act=not baseline)
    s.pop("history", None)
    return s


@server.tool(description="按策略走一个月的决策并执行（不推进时间），返回做了什么、为什么。")
def step() -> dict[str, Any]:
    return runner.step(bridge, runner.Memory())


@server.tool(description="策略本月会怎么做、为什么（不执行）。")
def advise() -> dict[str, Any]:
    snap, plan = runner.advise(bridge)
    return {"date": str(snap.date), "country": snap.name, "plan": plan.summary(12)}


@server.tool(description=(
    "实时局面（经桥接层，约 1.5 秒）：日期、国库与收支、GDP、建造力、税级、法律、市场价格，"
    "以及各州（人口、基础设施、可招劳动力）与建筑（等级、雇佣、利润率、能否扩建）。states_limit 控制输出几个州。"
))
def get_state(states_limit: int = 8, buildings: bool = True) -> dict[str, Any]:
    snap = observe.snapshot(bridge, with_buildings=buildings)
    states_out = []
    for s in sorted(snap.states, key=lambda s: -(s.population or 0))[:states_limit]:
        states_out.append({
            "id": s.id, "name": s.name, "population": s.population, "labor": s.labor,
            "incorporated": s.incorporated, "infrastructure": s.infrastructure,
            "infrastructure_usage": s.infrastructure_usage, "free_arable": s.free_arable,
            "buildings": [{"building": k, "levels": r.levels, "queued": r.queued, "employment": r.employment,
                           "profitability": r.profitability, "can_queue": r.can_queue}
                          for k, r in s.buildings.items() if r.levels or r.queued]})
    return {"date": str(snap.date), "country": snap.name, **snap.country, "tax_level": snap.tax_level,
            "researching": snap.researching, "laws": {g: l.key or l.name for g, l in snap.laws.items()},
            "prices": snap.prices, "states": states_out}


@server.tool(description=(
    "手动下发一个玩家动作（与点界面按钮等价，执行前后各读一次确认）。kind 取："
    "set_tax(level: VeryLow/Low/Medium/High/VeryHigh)、research(tech)、enact_law(law)、"
    "build(state: 州 id, building)、set_pm(state, building, pm)、"
    "reform_government(government: 改组后全部在朝利益集团的名字，逗号分隔，如「士大夫,军队,乡村民众」)；"
    "以及参数放在 params 里的：" + "；".join(f"{k}({v})" for k, v in ACT_PARAMS.items()) + "。"
    "command 可执行 docs/actions.md 清单里的任意命令：cmd 是命令表达式，probe 是执行前后各读一次的表达式，"
    "path 是上下文路径 [[列表, 下标], ...]，target 给定时要求读到它。"
))
def act(kind: str, level: str = "", tech: str = "", law: str = "", state: int = 0, building: str = "",
        pm: str = "", government: str = "", params: dict[str, Any] | None = None) -> dict[str, Any]:
    a = Actions(bridge)
    if kind in ACT_PARAMS:
        try:
            r = getattr(a, kind)(**(params or {}))
        except (TypeError, ValueError) as e:
            return {"ok": False, "error": f"{kind} 参数不对：{e}", "params": ACT_PARAMS[kind]}
    elif kind == "set_tax":
        r = a.set_tax(level)
    elif kind == "research":
        r = a.research(tech)
    elif kind == "reform_government":
        igs = {ig.name: ig.index for ig in observe.interest_groups(bridge)}
        names = [n.strip() for n in government.replace("，", ",").split(",") if n.strip()]
        unknown = [n for n in names if n not in igs]
        if unknown or not names:
            return {"ok": False, "error": f"不认识的利益集团 {unknown}", "interest_groups": list(igs)}
        r = a.reform_government([igs[n] for n in names])
    else:
        snap = observe.snapshot(bridge)
        if kind == "enact_law":
            r = a.enact_law(law, snap)
        elif kind == "build":
            r = a.build(state, building, snap)
        elif kind == "set_pm":
            r = a.set_pm(state, building, pm, snap)
        else:
            return {"ok": False, "error": f"不认识的动作 {kind}"}
    return {"ok": r.ok, "action": r.action, "detail": r.detail, "before": r.before, "after": r.after}


@server.tool(description="进行中的日志条目与其按钮、可见的决议；用 act(kind=press_button / take_decision) 执行。")
def journal() -> dict[str, Any]:
    try:
        return Actions(bridge).journal()
    except (GameError, BridgeError) as e:
        return {"ok": False, "error": str(e)}


@server.tool(description="政府（private=true 为私人）建造队列，按队列顺序；用 act(kind=move_construction / cancel_construction) 调整。")
def construction_queue(private: bool = False) -> list[dict[str, Any]] | dict[str, Any]:
    try:
        return Actions(bridge).construction_queue(private)
    except (GameError, BridgeError) as e:
        return {"ok": False, "error": str(e)}


@server.tool(description="玩家待处理的事件（含弹窗事件）与可选项；用 act(kind=choose_event_option) 选择。")
def events() -> list[dict[str, Any]] | dict[str, Any]:
    try:
        return Actions(bridge).events()
    except (GameError, BridgeError) as e:
        return {"ok": False, "error": str(e)}


@server.tool(description=(
    "求一段界面表达式文本，如 \"[GetMetaPlayer.GetPlayedOrObservedCountry.GetGDP|2]\"。"
    "可用的函数见游戏控制台 dump_data_types 的输出（logs/data_types/）。"
))
def query(text: str) -> dict[str, Any]:
    try:
        raw = bridge.read(text)
        return {"ok": True, "raw": raw, "text": plain(raw)}
    except (GameError, BridgeError) as e:
        return {"ok": False, "error": str(e)}


@server.tool(description="启动游戏（不经启动器，-debug_mode）并注入桥接层；save 为空时继续最近的存档。restart=true 先关掉正在运行的游戏。")
def launch_game(save: str = "", restart: bool = False) -> dict[str, Any]:
    out = launch(save=save, restart=restart, autosave="yearly")
    wait_in_game(bridge)
    return {"ok": True, "output": out.strip()[-400:]}


@server.tool(description="桥接层是否在线，以及定位到的游戏函数。")
def health() -> dict[str, Any]:
    try:
        return bridge.health()
    except BridgeError as e:
        return {"ok": False, "error": str(e)}


def _shape(v: Any) -> str:
    if isinstance(v, dict):
        return f"block({len(v)})"
    if isinstance(v, list):
        return f"list({len(v)})"
    return repr(v)[:40]


if __name__ == "__main__":
    server.run()
