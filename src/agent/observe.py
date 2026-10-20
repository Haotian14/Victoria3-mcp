"""实时局面：经桥接层按界面表达式读取，几十次往返、一两秒拿全。

与 state.py（解析整个存档，约 20 秒）互为补充：日常决策用这里，存档解析作兜底与核对。
数值一律是界面上同一个函数的结果（GetWeeklyIncome 等），口径与玩家看到的一致。

列表项带「路径」：(列表语句, 下标)。动作层（actions.py）拿同一条路径在那一项上执行，
执行前用键（BuildingType.GetKey 等）核对，避免列表在两次请求之间变了。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agent import gamedata
from agent.bridge import FIELD_ERROR, PLAYER, PLAYER_MUT, Bridge, number, plain
from agent.game import Date

STATES = f"{PLAYER_MUT}.AccessStates"

# 一个州里能建 / 能扩建的建筑分散在几个列表里（与界面上的分组一致）
BUILDING_LISTS = (
    "State.AccessBuildings",                # 已有的
    "State.GetPotentialUrbanBuildings",     # 城市建筑（含未建的）
    "State.AccessUncappedRuralBuildings",   # 农场、种植园
    "State.AccessCappedRuralBuildings",     # 矿、林场、渔场（受资源上限）
    "State.AccessDevelopmentBuildings",     # 港口、铁路、大学、建造部门……
)

LAW_LISTS = ("AccessActivePowerStructureLaws", "AccessActiveEconomyLaws", "AccessActiveHumanRightsLaws",
             "AccessActiveOtherLaws")

TAX_LEVELS = ("VeryLow", "Low", "Medium", "High", "VeryHigh")

COUNTRY_FIELDS = {
    "money": "GetGoldReserves",
    "gold_limit": "GetGoldReserveLimit",
    "credit_max": "GetMaxCredit",
    "credit_left": "GetRemainingCredit",
    "income": "GetWeeklyIncome",
    "expenses": "GetWeeklyExpenses",
    "balance": "GetWeeklyBalance",
    "gdp": "GetGDP",
    "population": "GetTotalPopulation",
    "construction": "CalcBaseConstructionSpeed",
    "construction_used": "CalcUsedConstruction",
    "sol": "GetAverageSoLByPopulation",
    "literacy": "GetIncorporatedLiteracyRate",
    "prestige": "GetPrestige",
    "legitimacy": "GetGovernmentLegitimacy",
    "queue_government": "GetNumGovernmentConstructionsInQueue",
    "queue_private": "GetNumPrivateConstructionsInQueue",
}


@dataclass
class BuildingRow:
    key: str
    path: list[tuple[str, int]]     # 从国家到这一项的列表路径
    levels: int
    queued: int                     # 排队中的扩建级数
    employment: float | None        # 0..1
    profitability: float | None     # 界面上的百分比
    cash: float | None
    can_queue: bool                 # IsValid(Building.QueueConstruction)


@dataclass
class StateRow:
    index: int                      # 在 AccessStates 里的下标
    id: int
    name: str
    infrastructure: float | None
    infrastructure_usage: float | None
    free_arable: int | None
    population: float | None
    gdp: float | None
    buildings: dict[str, BuildingRow] = field(default_factory=dict)

    @property
    def path(self) -> list[tuple[str, int]]:
        return [(STATES, self.index)]


@dataclass
class LawRow:
    group: str
    key: str | None                 # 由中文名对回游戏 id；对不上时为 None
    name: str
    path: list[tuple[str, int]]


@dataclass
class Snapshot:
    date: Date
    name: str
    country: dict[str, float | None]
    tax_level: str | None
    researching: str | None         # 正在研究的科技 id
    laws: dict[str, LawRow]         # 法律组 → 现行法律
    prices: dict[str, dict[str, float | None]]   # 商品 → price / base / buy / sell
    states: list[StateRow]

    def state(self, sid: int) -> StateRow | None:
        return next((s for s in self.states if s.id == sid), None)


def _f(text: str | None) -> float | None:
    if text is None or text.startswith(FIELD_ERROR):
        return None
    return number(text)


def _name_index(kind: str) -> dict[str, str]:
    """中文名 → 游戏 id（法律、科技）。界面上的名字就是本地化文本。"""
    gd = gamedata.get()
    out = {}
    for key, row in gd.table(kind).items():
        for name in (row.get("name") or {}).values():
            out.setdefault(name, key)
    return out


def country(b: Bridge) -> tuple[str, dict[str, float | None], str | None, str | None, Date]:
    names = list(COUNTRY_FIELDS)
    exprs = [f"{PLAYER}.{COUNTRY_FIELDS[n]}|2" for n in names]
    exprs += [f"IsValid({PLAYER}.SetTaxLevel{t})" for t in TAX_LEVELS]
    exprs += [f"{PLAYER}.GetCurrentlyResearchedTechnology.GetNameNoFormatting",
              f"{PLAYER}.GetNameNoFormatting", "TimeKeeper.GetCurrentDate.GetString"]
    vals = b.read_many(exprs)
    out = {n: _f(v) for n, v in zip(names, vals)}
    tax_valid = vals[len(names):len(names) + len(TAX_LEVELS)]
    # 现行税级的「设为该级」命令不可用；其余可用
    invalid = [t for t, v in zip(TAX_LEVELS, tax_valid) if v == "0"]
    tax = invalid[0] if len(invalid) == 1 else None
    tech_name = vals[-3]
    tech = _name_index("technologies").get(plain(tech_name)) if tech_name else None
    return plain(vals[-2] or ""), out, tax, tech, Date.parse(vals[-1] or "")


def laws(b: Bridge) -> dict[str, LawRow]:
    by_name = _name_index("laws")
    out: dict[str, LawRow] = {}
    for lst in LAW_LISTS:
        full = f"{PLAYER_MUT}.{lst}"
        for i, (group, name) in enumerate(b.rows(full, ["Law.GetGroup.GetKey", "Law.GetLawType.GetName"])):
            n = plain(name)
            out[group] = LawRow(group, by_name.get(n), n, [(full, i)])
    return out


def prices(b: Bridge) -> dict[str, dict[str, float | None]]:
    rows = b.rows(f"{PLAYER_MUT}.AccessFirstMarket.GetGoodsSortedByBalance",
                  ["Goods.GetKey", "Goods.GetMarketPrice|2", "Goods.GetBasePrice|2",
                   "Goods.GetMarketBuyOrders|1", "Goods.GetMarketSellOrders|1"])
    return {r[0]: {"price": _f(r[1]), "base": _f(r[2]), "buy": _f(r[3]), "sell": _f(r[4])} for r in rows}


STATE_FIELDS = ["State.GetID", "State.GetNameNoFormatting", "State.GetInfrastructure|1",
                "State.GetInfrastructureUsage|1", "State.GetNumFreeArableLand", "State.GetPopulationSize",
                "State.GetYearlyGDP|0"]

BUILDING_FIELDS = ["Building.GetBuildingType.GetKey", "Building.GetTotalLevels", "Building.GetExpansionLevelsInQueue",
                   "Building.GetEmploymentPercentage|3", "Building.GetProfitability|1",
                   "Building.GetCurrentCashReserves|0", "IsValid(Building.QueueConstruction)"]


def states(b: Bridge, with_buildings: bool = True) -> list[StateRow]:
    out = []
    for i, r in enumerate(b.rows(STATES, STATE_FIELDS)):
        sid = _f(r[0])
        out.append(StateRow(i, int(sid) if sid is not None else -1, r[1], _f(r[2]), _f(r[3]),
                            int(_f(r[4]) or 0), _f(r[5]), _f(r[6])))
    if with_buildings:
        for s in out:
            buildings(b, s)
    return out


def buildings(b: Bridge, s: StateRow) -> None:
    """填 s.buildings：同一建筑出现在多个列表里时，以第一个（已有建筑列表）为准。"""
    for lst in BUILDING_LISTS:
        for j, r in enumerate(b.rows(lst, BUILDING_FIELDS, path=s.path)):
            key = r[0]
            if key.startswith(FIELD_ERROR) or key in s.buildings:
                continue
            s.buildings[key] = BuildingRow(
                key=key, path=s.path + [(lst, j)], levels=int(_f(r[1]) or 0), queued=int(_f(r[2]) or 0),
                employment=_f(r[3]), profitability=_f(r[4]), cash=_f(r[5]), can_queue=r[6] == "1")


def snapshot(b: Bridge, with_buildings: bool = True) -> Snapshot:
    name, c, tax, tech, date = country(b)
    return Snapshot(date=date, name=name, country=c, tax_level=tax, researching=tech, laws=laws(b),
                    prices=prices(b), states=states(b, with_buildings))
