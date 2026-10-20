"""MCP 入口。第一阶段只读：查静态数据、算建筑经济账、读存档。

- search / lookup          查游戏定义（中英文名或 id）
- rank_buildings           可建造建筑按每点建造力的增加值排序
- building_economics       单个建筑逐个生产方式组的账
- save_summary             读最近（或指定）的文本存档，列出顶层结构

动作执行（第二阶段，游戏内桥接层）完成前，这里不会改动游戏状态。

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

from agent import gamedata, paths, pdx, save  # noqa: E402
from agent.strategy import economy  # noqa: E402

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
    "techs 给定时只看已解锁的建筑与生产方式（自动补前置）；laws 给定时按法律过滤生产方式。"
    "prices 覆盖商品价格（默认基准价）。"
))
def rank_buildings(techs: list[str] | None = None, laws: list[str] | None = None,
                   prices: dict[str, float] | None = None, limit: int = 20) -> list[dict[str, Any]]:
    gd = gamedata.get()
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


def _shape(v: Any) -> str:
    if isinstance(v, dict):
        return f"block({len(v)})"
    if isinstance(v, list):
        return f"list({len(v)})"
    return repr(v)[:40]


if __name__ == "__main__":
    server.run()
