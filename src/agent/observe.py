"""实时局面：经桥接层按界面表达式读取，几十次往返、一两秒拿全。

与 state.py（解析整个存档，约 20 秒）互为补充：日常决策用这里，存档解析作兜底与核对。
数值一律是界面上同一个函数的结果（GetWeeklyIncome 等），口径与玩家看到的一致。

列表项带「路径」：(列表语句, 下标)。动作层（actions.py）拿同一条路径在那一项上执行，
执行前用键（BuildingType.GetKey 等）核对，避免列表在两次请求之间变了。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent import gamedata
from agent.bridge import FIELD_ERROR, IGS, PLAYER, PLAYER_MUT, Bridge, number, plain
from agent.game import Date

STATES = f"{PLAYER_MUT}.AccessStates"
INSTITUTIONS = f"{PLAYER_MUT}.AccessInstitutions"

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
    "tag": "GetTagName",
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
    "tax_waste": "GetAverageTaxWaste",           # 官僚不足时上升：建政府行政机构的信号
    "unrealized_taxes": "GetUnrealizedTaxes",
    "authority": "GetPowerDelta('authority')",   # 可用权威力（顶栏数字）
    "subsidies": "GetSubsidiesExpenses",         # 每周补贴支出（预算面板合计）
}

# 消费税候选：先奢侈品，不碰谷物/布料等民生品（1.13 权威成本见财政调研）
CONSUMPTION_TAX_GOODS = ("tea", "liquor", "opium", "tobacco", "sugar", "porcelain")

# 贸易政策观测：七档互斥，同一商品同一方向只有一个生效
TRADE_WATCH_GOODS = ("meat", "wood", "groceries", "iron", "tools", "coal")
TRADE_POLICIES = ("TariffsNone", "TariffsLow", "TariffsHigh", "TariffsMax",
                  "SubventionsLow", "SubventionsHigh", "SubventionsMax")


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
    wage_rate: float | None = None  # GetWageRate：每 1000 名雇员每周的工资基数
    employed: float | None = None   # 现有雇员数
    can_privatize: bool = False     # 私有化开关当前是否打开（CanBePrivatized）
    can_toggle_privatization: bool = False   # 是否具备私有化资格（IsValid(TogglePrivatization)）
    subsidized: bool = False        # 正在接受政府补贴（IsSubsidized）
    subsidy_cost: float = 0.0       # 每周补贴支出（GetSubsidies；未补贴为 0）
    earnings: float = 0.0           # 每周收入（已扣投入品）
    wages_expense: float = 0.0      # 每周工资
    tariffs_paid: float = 0.0
    tolls_paid: float = 0.0

    @property
    def profit(self) -> float:
        """实际现金流（每级建筑合计，非“相对生产率”）。"""
        return self.earnings - self.wages_expense - self.tariffs_paid - self.tolls_paid


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
    incorporated: bool = True
    isolated: bool = False          # 与市场不连通
    unemployed: float = 0.0         # 失业的劳动年龄人口
    tax_capacity: float | None = None       # 州征税能力（CalcTaxCapacity）
    tax_capacity_usage: float | None = None  # 已用掉的征税能力（超过即税收浪费）
    famine: bool = False                    # 州正在闹饥荒（State.HasFamine）
    incorporating: bool = False             # 正在并入（State.IsIncorporating）
    incorporation_progress: float = 0.0
    can_incorporate: bool = False           # IsValid(IncorporateState)
    buildings: dict[str, BuildingRow] = field(default_factory=dict)

    @property
    def labor(self) -> float:
        """可招的人：失业 + 自给农业里的农民（新建筑从他们中招人）。"""
        return self.unemployed + sum(b.employed or 0 for k, b in self.buildings.items() if "subsistence" in k)

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
class IGRow:
    index: int                      # 在 IGS 列表里的下标（改组政府按它）
    name: str
    clout: float
    in_gov: bool
    marginal: bool


@dataclass
class LawOption:
    """路线上的一条目标法律：游戏给的能否推行、预计每个检查点的结果概率、各利益集团的态度。"""
    group: str
    key: str
    name: str
    path: list[tuple[str, int]]
    valid: bool                     # IsValid(Law.StartEnacting)
    why_not: str                    # 不能推行时游戏给的原因
    success: float                  # 每个检查点：推进 / 有利事件 / 受阻 / 辩论
    advance: float
    stall: float
    debate: float
    stance: dict[str, int] = field(default_factory=dict)   # 利益集团名 → 立法时 +1 支持 / -1 反对 / 0 中立

    @property
    def support_only(self) -> bool:
        """唯一的障碍是「立法成功概率高于 0%」：缺的是政府里的支持者，不是科技或前置法律。"""
        parts = [p for p in self.why_not.split("；") if p]
        return not self.valid and bool(parts) and all(CHANCE_REQUIREMENT in p for p in parts)


CHANCE_REQUIREMENT = "立法成功概率高于0%"


@dataclass
class Snapshot:
    date: Date
    name: str
    country: dict[str, Any]           # 数值字段 + tag（字符串）
    tax_level: str | None
    researching: str | None         # 正在研究的科技 id
    laws: dict[str, LawRow]         # 法律组 → 现行法律
    prices: dict[str, dict[str, float | None]]   # 商品 → price / base / buy / sell
    states: list[StateRow]
    igs: list[IGRow] = field(default_factory=list)
    institutions: list[str] | None = None      # 已解锁的机构（教育要等学校法才会出现）
    taxed_goods: set[str] | None = None        # 已开征消费税的商品
    trade_policies: dict[str, dict[str, str]] | None = None   # 商品 → {Import/Export: 当前档位}

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
    exprs = [f"{PLAYER}.{COUNTRY_FIELDS[n]}" + ("" if n == "tag" else "|2") for n in names]
    exprs += [f"IsValid({PLAYER}.SetTaxLevel{t})" for t in TAX_LEVELS]
    exprs += [f"{PLAYER}.GetCurrentlyResearchedTechnology.GetNameNoFormatting",
              f"{PLAYER}.GetNameNoFormatting", "TimeKeeper.GetCurrentDate.GetString"]
    vals = b.read_many(exprs)
    out = {n: _f(v) for n, v in zip(names, vals)}
    out["tag"] = plain(vals[names.index("tag")] or "")
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
                "State.GetYearlyGDP|0", "State.IsIncorporated", "State.IsIsolatedFromMarket",
                "State.GetNumUnemployedWorkingAdults", "State.CalcTaxCapacity|2", "State.CalcTaxCapacityUsage|2",
                "State.HasFamine", "State.IsIncorporating", "State.GetIncorporationProgress|3",
                "IsValid(State.IncorporateState)"]

BUILDING_FIELDS = ["Building.GetBuildingType.GetKey", "Building.GetTotalLevels", "Building.GetExpansionLevelsInQueue",
                   "Building.GetEmploymentPercentage|3", "Building.GetProfitability|1",
                   "Building.GetCurrentCashReserves|0", "IsValid(Building.QueueConstruction)",
                   "Building.GetWageRate|3", "Building.GetNoOfEmployed", "Building.CanBePrivatized",
                   "Building.IsSubsidized", "Building.GetSubsidies|1",
                   "Building.GetEarnings|2", "Building.GetLastWagesExpenses|2",
                   "Building.GetTariffsPaid|2", "Building.GetTollsPaid|2",
                   "IsValid(Building.TogglePrivatization)"]


def states(b: Bridge, with_buildings: bool = True) -> list[StateRow]:
    out = []
    for i, r in enumerate(b.rows(STATES, STATE_FIELDS)):
        sid = _f(r[0])
        out.append(StateRow(i, int(sid) if sid is not None else -1, r[1], _f(r[2]), _f(r[3]),
                            int(_f(r[4]) or 0), _f(r[5]), _f(r[6]), incorporated=r[7] == "1",
                            isolated=r[8] == "1", unemployed=_f(r[9]) or 0.0,
                            tax_capacity=_f(r[10]), tax_capacity_usage=_f(r[11]), famine=r[12] == "1",
                            incorporating=r[13] == "1", incorporation_progress=_f(r[14]) or 0.0,
                            can_incorporate=r[15] == "1"))
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
                employment=_f(r[3]), profitability=_f(r[4]), cash=_f(r[5]), can_queue=r[6] == "1",
                wage_rate=_f(r[7]) if row_built(r) else None, employed=_f(r[8]),
                can_privatize=r[9] == "1", subsidized=r[10] == "1", subsidy_cost=_f(r[11]) or 0.0,
                earnings=_f(r[12]) or 0.0, wages_expense=_f(r[13]) or 0.0,
                tariffs_paid=_f(r[14]) or 0.0, tolls_paid=_f(r[15]) or 0.0,
                can_toggle_privatization=r[16] == "1")


def row_built(r: list[str]) -> bool:
    """已建成（有等级）的建筑才有有意义的工资率。"""
    return (_f(r[1]) or 0) > 0


def researched(b: Bridge) -> set[str]:
    """已研究的科技：一次往返把全部科技问一遍。"""
    keys = list(gamedata.get().techs)
    vals = b.read_many([f"GetTechnology('{k}').HasResearchedTech({PLAYER}.Self)" for k in keys])
    return {k for k, v in zip(keys, vals) if v == "1"}


_costs: dict[str, float] = {}


def construction_costs(b: Bridge) -> dict[str, float]:
    """每种建筑的建造点数（GetRequiredConstruction），整局不变，读一次缓存。"""
    if not _costs:
        keys = [k for k, v in gamedata.get().buildings.items() if v.get("buildable")]
        vals = b.read_many([f"GetBuildingType('{k}').GetRequiredConstruction|1" for k in keys])
        _costs.update({k: float(v) for k, v in zip(keys, vals) if v and _f(v)})
    return _costs


def interest_groups(b: Bridge) -> list[IGRow]:
    rows = b.rows(IGS, ["InterestGroup.GetNameNoFormatting", "InterestGroup.GetCloutAsFloat|3",
                        "InterestGroup.IsInGovernment", "InterestGroup.IsMarginal"])
    return [IGRow(i, plain(r[0]), _f(r[1]) or 0.0, r[2] == "1", r[3] == "1") for i, r in enumerate(rows)]


LAW_ALTERNATIVES = "Law.GetLawAlternatives"
CHANCE_FIELDS = ["IsValid(Law.StartEnacting)", "GetDesc(Law.StartEnacting)", "Law.GetCheckpointSuccessChance|3",
                 "Law.GetCheckpointAdvanceChance|3", "Law.GetCheckpointStallChance|3", "Law.GetCheckpointDebateChance|3"]
# 立法时集团的支持 / 反对（成功率、受阻率按它算）。注意不是 GetApprovalValueIfEnacted：
# 后者是推行后的认可度，大清的乡村民众对佃农制认可度不变，却是支持者（把它拉进政府后推进率正好 +9.8%）
STANCE_FIELDS = ["InterestGroup.GetNameNoFormatting", "InterestGroup.IsEndorsingLawEnactment(Law.Self)",
                 "InterestGroup.IsOpposingLawEnactment(Law.Self)"]


def law_options(b: Bridge, current: dict[str, LawRow], targets: list[tuple[str, str]]) -> list[LawOption]:
    """targets：路线 [(法律组, 法律 id)]，跳过已是现行法律的。成功率是游戏按当前政府、君主、运动算的预计值；
    态度是游戏判定的各集团立法时支持 / 反对（含集团领袖的意识形态）。"""
    gd = gamedata.get()
    out: list[LawOption] = []
    for group, law in targets:
        row = current.get(group)
        info = gd.laws.get(law)
        if row is None or info is None or row.key == law:
            continue
        names = set((info.get("name") or {}).values())
        alts = [plain(n) for (n,) in b.rows(LAW_ALTERNATIVES, ["Law.GetLawType.GetName"], path=row.path)]
        idx = next((i for i, n in enumerate(alts) if n in names), None)
        if idx is None:
            continue
        path = row.path + [(LAW_ALTERNATIVES, idx)]
        v = b.read_many(CHANCE_FIELDS, path)
        opt = LawOption(group, law, alts[idx], path, v[0] == "1", plain(v[1] or ""),
                        _f(v[2]) or 0.0, _f(v[3]) or 0.0, _f(v[4]) or 0.0, _f(v[5]) or 0.0)
        for n, endorse, oppose in b.rows(IGS, STANCE_FIELDS, path=path):
            opt.stance[plain(n)] = (endorse == "1") - (oppose == "1")
        out.append(opt)
    return out


def trade_policies(b: Bridge) -> dict[str, dict[str, str]]:
    """每个观察商品当前的进口/出口政策档位（HasImportTariffsNone 等七选一）。"""
    exprs, keys = [], []
    for g in TRADE_WATCH_GOODS:
        for side in ("Import", "Export"):
            for p in TRADE_POLICIES:
                exprs.append(f"{PLAYER}.Has{side}{p}(GetGoods('{g}').Self)")
                keys.append((g, side, p))
    vals = b.read_many(exprs)
    out: dict[str, dict[str, str]] = {g: {} for g in TRADE_WATCH_GOODS}
    for (g, side, p), v in zip(keys, vals):
        if v == "1":
            out[g][side] = p
    return out


def snapshot(b: Bridge, with_buildings: bool = True) -> Snapshot:
    name, c, tax, tech, date = country(b)
    taxed = {g for g, v in zip(CONSUMPTION_TAX_GOODS,
                               b.read_many([f"GetGoods('{g}').IsTaxed({PLAYER})"
                                            for g in CONSUMPTION_TAX_GOODS])) if v == "1"}
    return Snapshot(date=date, name=name, country=c, tax_level=tax, researching=tech, laws=laws(b),
                    prices=prices(b), states=states(b, with_buildings), igs=interest_groups(b),
                    institutions=[plain(r[0]) for r in b.rows(INSTITUTIONS, ["Institution.GetNameNoFormatting"])],
                    taxed_goods=taxed, trade_policies=trade_policies(b))
