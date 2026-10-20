"""建筑经济账：每级建筑每周的增加值（产出 − 投入，按商品价格），以及每点建造力的回报。

生产方式在游戏里是按组叠加的修正（基础组 + 自动化组 + 副产品组……），
所以逐组独立挑「已解锁且增加值最高」的那个，再加总。

价格默认用商品基准价（goods.cost）；有存档后换成本国市场的实际价格。
工资随市场浮动，静态数据里没有，所以这里只算增加值，不算利润 ——
`per_worker` 给出劳动生产率，供调用方对照本国工资水平。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agent.gamedata import GameData


@dataclass
class PmChoice:
    pmg: str
    pm: str
    value_added: float


@dataclass
class BuildingEconomics:
    building: str
    construction: float | None
    value_added: float                       # 每级每周
    workers: float                           # 每级满员
    inputs: dict[str, float] = field(default_factory=dict)
    outputs: dict[str, float] = field(default_factory=dict)
    choices: list[PmChoice] = field(default_factory=list)

    @property
    def per_construction(self) -> float | None:
        if not self.construction:
            return None
        return self.value_added / self.construction

    @property
    def per_worker(self) -> float | None:
        return self.value_added / self.workers if self.workers else None


def pm_unlocked(gd: GameData, pm: str, techs: set[str] | None, laws: set[str] | None) -> bool:
    """techs / laws 为 None 表示不按该项过滤。"""
    d = gd.pms.get(pm)
    if d is None:
        return False
    if techs is not None and not set(d["techs"]) <= techs:
        return False
    if laws is not None:
        if d["unlocking_laws"] and not set(d["unlocking_laws"]) & laws:
            return False
        if set(d["disallowing_laws"]) & laws:
            return False
    return True


def pm_value(gd: GameData, pm: str, prices: dict[str, float]) -> float:
    d = gd.pms[pm]
    out = sum(q * prices.get(g, 0.0) for g, q in d["outputs"].items())
    inp = sum(q * prices.get(g, 0.0) for g, q in d["inputs"].items())
    return out - inp


def building_economics(gd: GameData, building: str, prices: dict[str, float] | None = None,
                       techs: set[str] | None = None,
                       laws: set[str] | None = None) -> BuildingEconomics:
    prices = prices or gd.base_prices()
    b = gd.buildings[building]
    econ = BuildingEconomics(building, b.get("construction"), 0.0, 0.0)
    for pmg in b["pmgs"]:
        options = [pm for pm in (gd.pmgs.get(pmg) or {}).get("pms", [])
                   if pm_unlocked(gd, pm, techs, laws)]
        if not options:
            continue
        best = max(options, key=lambda pm: pm_value(gd, pm, prices))
        d = gd.pms[best]
        va = pm_value(gd, best, prices)
        econ.choices.append(PmChoice(pmg, best, va))
        econ.value_added += va
        econ.workers += sum(d["employment"].values())
        for g, q in d["inputs"].items():
            econ.inputs[g] = econ.inputs.get(g, 0) + q
        for g, q in d["outputs"].items():
            econ.outputs[g] = econ.outputs.get(g, 0) + q
    return econ


def rank_buildings(gd: GameData, prices: dict[str, float] | None = None,
                   techs: set[str] | None = None, laws: set[str] | None = None,
                   limit: int = 20) -> list[BuildingEconomics]:
    """可建造建筑按每点建造力的增加值排序。techs 给定时只看已解锁的建筑。"""
    rows = []
    for key, b in gd.buildings.items():
        if not b.get("buildable") or not b.get("construction"):
            continue
        if techs is not None and not set(b["techs"]) <= techs:
            continue
        econ = building_economics(gd, key, prices, techs, laws)
        if econ.outputs:
            rows.append(econ)
    rows.sort(key=lambda e: e.per_construction or 0.0, reverse=True)
    return rows[:limit]
