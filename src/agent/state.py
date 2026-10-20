"""从存档里取出玩家国家的局面，压成策略层用得上的精简结构。

存档里的关联全靠数字 id（国家 156、州 963、市场 49），商品按定义顺序编号
（`7` = grain）；这里一律换成游戏内部名，调用方不用再管编号。

结构对照 1.13.11 的文本存档（`-debug_mode` 启动后保存）：
- player_manager.database.*.country           玩家国家 id
- country_manager.database[id].budget         国库 money、current_price_report（本地价格）
- technology.database[*].acquired_technologies（按 country 找）
- laws.database[*]                            law / country / active
- states.database[id]                         region、arable_land、infrastructure
- building_manager.database[*]                building / state / levels / production_methods ……
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from agent import save
from agent.gamedata import GameData


@dataclass
class Building:
    id: str
    building: str
    state: int
    levels: int
    pms: list[str]
    staffing: float
    profit: float | None
    cash_reserves: float | None


@dataclass
class State:
    id: int
    region: str
    arable_land: int | None
    infrastructure: float | None
    infrastructure_usage: float | None
    buildings: list[Building] = field(default_factory=list)


@dataclass
class CountryState:
    date: str
    country_id: int
    tag: str
    name: str | None
    government: str | None
    tax_level: str | None
    money: float | None
    credit: float | None
    weekly_income: float
    weekly_expense: float
    base_wage: float | None
    prices: dict[str, float]          # 本国市场价格（current_price_report）
    world_prices: dict[str, float]    # 世界市场价格（price_trend 最新值）
    techs: set[str]
    laws: set[str]
    states: list[State]

    def buildings(self) -> list[Building]:
        return [b for s in self.states for b in s.buildings]


def player_country_id(gs: dict[str, Any]) -> int:
    players = (gs.get("player_manager") or {}).get("database") or {}
    for p in players.values():
        if isinstance(p, dict) and "country" in p:
            return int(p["country"])
    prev = gs.get("previous_played")
    if isinstance(prev, list) and prev and isinstance(prev[0], dict):
        return int(prev[0]["idtype"])
    raise ValueError("存档里找不到玩家国家（player_manager / previous_played 都为空）")


def _goods_by_index(gd: GameData) -> dict[int, str]:
    return {v["index"]: k for k, v in gd.goods.items() if "index" in v}


def _goods_values(block: Any, by_index: dict[int, str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for idx, row in ((block or {}).get("goods") or {}).items():
        name = by_index.get(int(idx))
        if name is not None and isinstance(row, dict) and "value" in row:
            out[name] = float(row["value"])
    return out


def _world_prices(gs: dict[str, Any], by_index: dict[int, str]) -> dict[str, float]:
    channels = (((gs.get("market_manager") or {}).get("world_market") or {})
                .get("price_trend") or {}).get("channels") or {}
    out = {}
    for idx, ch in channels.items():
        name = by_index.get(int(idx))
        values = (ch or {}).get("values")
        if name and isinstance(values, list) and values:
            out[name] = float(values[-1])
    return out


def _find_by_country(db: dict[str, Any], country: int) -> list[dict[str, Any]]:
    return [v for v in db.values() if isinstance(v, dict) and v.get("country") == country]


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) else None


def extract(gs: dict[str, Any], gd: GameData, country_id: int | None = None) -> CountryState:
    cid = country_id if country_id is not None else player_country_id(gs)
    country = gs["country_manager"]["database"][str(cid)]
    budget = country.get("budget") or {}
    by_index = _goods_by_index(gd)

    techs: set[str] = set()
    for row in _find_by_country((gs.get("technology") or {}).get("database") or {}, cid):
        techs.update(row.get("acquired_technologies") or [])

    laws = {row["law"] for row in _find_by_country((gs.get("laws") or {}).get("database") or {}, cid)
            if row.get("active")}

    state_ids = [int(s) for s in country.get("states") or []]
    state_db = (gs.get("states") or {}).get("database") or {}
    states: dict[int, State] = {}
    for sid in state_ids:
        s = state_db.get(str(sid)) or {}
        states[sid] = State(sid, s.get("region", "?"), s.get("arable_land"),
                            _num(s.get("infrastructure")), _num(s.get("infrastructure_usage")))

    for bid, b in ((gs.get("building_manager") or {}).get("database") or {}).items():
        if not isinstance(b, dict) or b.get("state") not in states:
            continue
        states[b["state"]].buildings.append(Building(
            id=bid, building=b.get("building", "?"), state=b["state"],
            levels=int(b.get("levels") or 0), pms=list(b.get("production_methods") or []),
            staffing=float(b.get("staffing") or 0),
            profit=_num(b.get("profit_after_reserves")), cash_reserves=_num(b.get("cash_reserves")),
        ))

    name = (gs.get("meta_data") or {}).get("name") if cid == _safe_player(gs) else None
    return CountryState(
        date=str(gs.get("date")),
        country_id=cid,
        tag=country.get("definition", "?"),
        name=name,
        government=country.get("government"),
        tax_level=country.get("tax_level"),
        money=_num(budget.get("money")),
        credit=_num(budget.get("credit")),
        weekly_income=sum(x for x in budget.get("weekly_income") or [] if isinstance(x, (int, float))),
        weekly_expense=sum(x for x in budget.get("weekly_expenses") or [] if isinstance(x, (int, float))),
        base_wage=_num(budget.get("base_wage")),
        prices=_goods_values(budget.get("current_price_report"), by_index),
        world_prices=_world_prices(gs, by_index),
        techs=techs,
        laws=laws,
        states=list(states.values()),
    )


def _safe_player(gs: dict[str, Any]) -> int | None:
    try:
        return player_country_id(gs)
    except ValueError:
        return None


# ---------------------------------------------------------------- 读存档（带缓存）

_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def load_gamestate(path: str) -> dict[str, Any]:
    """整档解析约 15 秒（100MB），按修改时间缓存，存档没变就不重读。"""
    mtime = os.path.getmtime(path)
    hit = _cache.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    gs = save.load(path)
    _cache.clear()
    _cache[path] = (mtime, gs)
    return gs
