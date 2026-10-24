"""生产方式：已建成的建筑按「增加值 − 工资」挑每组最赚钱的已解锁方式。

- 只在差距明显时换：目标方式利润领先 SWITCH_MARGIN 以内的都算「可接受」，现行方式在其中就不动；
  换过的建筑 runner 冷却 24 个月。普鲁士自测里 10% 的门槛不够：纺织厂在两种方式间来回切了 34 次 ——
  自己一产出，那种商品就跌价，「最优」又翻回去，每次切换还有一段适应期的减产；
- 产出不是商品的方式组不碰（建造部门、行政机构）：模型只看得到投入成本、看不到建造点数，
  会把铁框架降回木制（普鲁士自测建造力因此从 45 掉到 24）；
- 投入在本国市场上没人卖（卖单为 0）的方式不选，否则一换就短缺；
- 每月最多处理 MAX_PER_MONTH 个建筑（按等级从大到小轮流），读列表很费往返。
"""

from __future__ import annotations

from agent.gamedata import GameData
from agent.observe import Snapshot
from agent.strategy import economy
from agent.strategy.config import Decision, cfg, profile
from agent.strategy.construction import SECTOR, _prices, _wage_rates

UNIVERSITY = "building_university"
FINANCIAL = "building_financial_district"
FINANCIAL_PRIVATE = "pm_financial_district_privately_owned"
# 1.13 调研里 PM 错配最严重、收益最大的行业：每月优先扫，不让庄园/生存农场挤掉
PM_PRIORITY = ("building_paper_mill", "building_furniture_manufactory", "building_livestock_ranch",
               "building_tooling_workshop", "building_logging_camp", "building_fishing_wharf")

SWITCH_MARGIN = 0.25
MAX_PER_MONTH = 12
LOGGING = "building_logging_camp"


def employment_delta(gd: GameData, pm: str) -> int:
    """PM 的净雇佣变化：正数=增岗，负数=省人。游戏数据里减岗 PM 直接写负值。"""
    return sum(int(v) for v in (gd.pms.get(pm, {}).get("employment") or {}).values())


def labor_surplus(snap: Snapshot) -> bool:
    """自给农 + 失业是否超过人口阈值：大清早期几乎总是 True。"""
    spec = cfg().get("production") or {}
    ratio = float(spec.get("labor_surplus_ratio", 0.05))
    pop = snap.country.get("population") or 0.0
    return bool(pop and sum(s.labor for s in snap.states) > pop * ratio)


def _necessity_shortage(gd: GameData, pm: str, prices: dict[str, float],
                        base: dict[str, float]) -> bool:
    """该 PM 产出的必需品是否 >125% 基准价：短缺时可以破例机械化降成本。"""
    ratio = float((cfg().get("production") or {}).get("necessity_price_ratio", 1.25))
    return any(base.get(g) and prices.get(g, 0.0) > base[g] * ratio
               for g in gd.pms.get(pm, {}).get("outputs", ()))


def _price_ratio(prices: dict[str, float], base: dict[str, float], good: str) -> float:
    return prices.get(good, 0.0) / base[good] if base.get(good) else 999.0


def candidates(gd: GameData, snap: Snapshot, researched: set[str], offset: int = 0) -> list[Decision]:
    prices = _prices(gd, snap)
    base = gd.base_prices()
    jobs = labor_surplus(snap)
    laws = {l.key for l in snap.laws.values() if l.key}
    wages, wage_all = _wage_rates(snap)
    mix = cfg()["construction"]["wage_mix"]
    no_supply = {g for g, p in snap.prices.items() if not p.get("sell")}
    skip = set(cfg()["skip_buildings"])

    owned = [(s, key, row) for s in snap.states for key, row in s.buildings.items()
             if row.levels > 0 and key in gd.buildings and key not in skip and "subsistence" not in key]
    owned.sort(key=lambda t: -t[2].levels)
    if not owned:
        return []
    # 优先检查 PM 收益最大的行业；庄园/生存农场等级再高也不该占满每月名额
    priority = [t for t in owned if t[1] in PM_PRIORITY]
    priority.sort(key=lambda t: -t[2].levels)
    rest = [t for t in owned if t[1] not in PM_PRIORITY]
    start = offset % len(rest) if rest else 0
    rest = rest[start:] + rest[:start]
    owned = priority + rest

    out: list[Decision] = []
    for s, key, row in owned[:MAX_PER_MONTH]:
        wage = wages.get(s.id, wage_all) * mix / 10000.0
        for pmg in gd.buildings[key]["pmgs"]:
            options = [pm for pm in (gd.pmgs.get(pmg) or {}).get("pms", [])
                       if economy.pm_unlocked(gd, pm, researched, laws)
                       and not (set(gd.pms[pm]["inputs"]) & no_supply)]
            if len(options) < 2 or any(not gd.pms[pm]["outputs"] for pm in options):
                continue
            if jobs:
                # 就业优先：劳动力过剩时过滤净减岗 PM；必需品严重短缺时破例
                safe = [pm for pm in options
                        if employment_delta(gd, pm) >= 0 or _necessity_shortage(gd, pm, prices, base)]
                if safe:
                    options = safe
            ranked = sorted(options, key=lambda pm: economy.pm_profit(gd, pm, prices, wage), reverse=True)
            best = economy.pm_profit(gd, ranked[0], prices, wage)
            ok = [pm for pm in ranked if economy.pm_profit(gd, pm, prices, wage) >= best - abs(best) * SWITCH_MARGIN]
            out.append(Decision("set_pm", {"state": s.id, "building": key, "pm": ranked[0], "acceptable": ok},
                                f"{s.name} {pmg}：每级周利润 {best:,.0f}"))
    return out


def logging_candidates(gd: GameData, snap: Snapshot, researched: set[str]) -> list[Decision]:
    """攻略：大部分伐木营优先软木，保留 2–4 个州专注硬木，让硬木价格比软木高 50–60%，
    给建造预留软木产能。硬木太贵就多加一个州，太便宜就减一个。"""
    spec = profile(snap).get("logging") or {}
    soft, hard = spec.get("softwood_pm"), spec.get("hardwood_pm")
    if not soft or not hard:
        return []
    rows = [(s, s.buildings[LOGGING]) for s in snap.states
            if LOGGING in s.buildings and s.buildings[LOGGING].levels > 0]
    if not rows:
        return []
    rows.sort(key=lambda t: -t[1].levels)
    prices = _prices(gd, snap)
    base = gd.base_prices()
    ratio = _price_ratio(prices, base, "hardwood") / max(_price_ratio(prices, base, "wood"), 1e-6)
    n = int(spec.get("hardwood_states", 3))
    if ratio > float(spec.get("hardwood_price_ratio", 1.8)):
        n += 1
    elif ratio < 1.2:
        n -= 1
    n = max(int(spec.get("min_hardwood_states", 1)),
            min(int(spec.get("max_hardwood_states", 6)), n))
    laws = {l.key for l in snap.laws.values() if l.key}
    desired: list[Decision] = []
    for i, (s, row) in enumerate(rows):
        target = hard if i < n else soft
        if not economy.pm_unlocked(gd, target, researched, laws):
            continue
        desired.append(Decision(
            "set_pm", {"state": s.id, "building": LOGGING, "pm": target, "acceptable": [target]},
            f"{s.name} 伐木 → {'专注硬木' if i < n else '优先软木'}"
            f"（{row.levels} 级；硬木/软木价格比 {ratio:.2f}）"))
    if not desired:
        return []
    # 建筑行的当前 PM 不在快照里：按月轮转，保证软木州也能轮到，Actions 对已达标 PM 会跳过
    per = max(1, int(spec.get("max_per_month", 3)))
    start = (snap.date.month * per) % len(desired)
    return (desired[start:] + desired[:start])[:per]


def construction_pm_candidates(gd: GameData, snap: Snapshot, researched: set[str]) -> list[Decision]:
    """建造部门 PM：铁价 ≤75% 基准切铁框架；钢价 ≤基准且科技已研切钢框架。
    这部分不能走普通利润模型（建造部门不产商品），必须单独判断。"""
    spec = (cfg().get("construction") or {}).get("construction_pm") or {}
    iron, steel = spec.get("iron"), spec.get("steel")
    if not iron or not steel:
        return []
    base = gd.base_prices()
    prices = _prices(gd, snap)
    laws = {l.key for l in snap.laws.values() if l.key}
    target = ""
    iron_ratio = float(spec.get("iron_price_ratio", 0.75))
    early_year = int(spec.get("early_until_year", 0) or 0)
    if early_year and snap.date.year < early_year:
        iron_ratio = float(spec.get("early_iron_price_ratio", iron_ratio))
    if (economy.pm_unlocked(gd, steel, researched, laws)
            and _price_ratio(prices, base, "steel") <= float(spec.get("steel_price_ratio", 1.0))):
        target = steel
    elif (economy.pm_unlocked(gd, iron, researched, laws)
            and _price_ratio(prices, base, "iron") <= iron_ratio):
        target = iron
    if not target:
        return []
    rows = [(s, s.buildings[SECTOR]) for s in snap.states
            if SECTOR in s.buildings and s.buildings[SECTOR].levels > 0]
    rows.sort(key=lambda t: -t[1].levels)
    name = gd.pms[target]["name"].get("zh", target)
    return [Decision("set_pm", {"state": s.id, "building": SECTOR, "pm": target, "acceptable": [target]},
                     f"{s.name} 建造部门 → {name}（铁/钢价格已达标）")
            for s, _ in rows[:int(spec.get("max_per_month", 4))]]


def financial_candidates(gd: GameData, snap: Snapshot, researched: set[str]) -> list[Decision]:
    """金融区保持私人所有：每级 +50 资本家，是养大实业家最直接的单一杠杆。
    公开交易 PM（mutual_funds）会把 25 店主换成 25 官僚，对实业家更差，所以不选。"""
    if FINANCIAL not in gd.buildings or not economy.pm_unlocked(gd, FINANCIAL_PRIVATE, researched, None):
        return []
    out: list[Decision] = []
    for s in snap.states:
        row = s.buildings.get(FINANCIAL)
        if row is None or row.levels <= 0:
            continue
        out.append(Decision("set_pm", {"state": s.id, "building": FINANCIAL, "pm": FINANCIAL_PRIVATE,
                                       "acceptable": [FINANCIAL_PRIVATE]},
                            f"{s.name} 金融区 → 私人所有（每级 +50 资本家）"))
    return out


def university_candidates(gd: GameData, snap: Snapshot, researched: set[str]) -> list[Decision]:
    """大学：产出是创新、不是商品，经济账挑不了生产方式。按档案里的 pm_order 从低到高，
    取已解锁的最高一档（经院教育 → 哲学系 → 分析哲学系，创新 +50% / +100%）。"""
    order = (profile(snap).get("universities") or {}).get("pm_order") or []
    if not order:
        return []
    laws = {l.key for l in snap.laws.values() if l.key}
    out: list[Decision] = []
    for s in snap.states:
        row = s.buildings.get(UNIVERSITY)
        if row is None or row.levels <= 0:
            continue
        unlocked = [pm for pm in order if pm in gd.pms and economy.pm_unlocked(gd, pm, researched, laws)]
        if not unlocked:
            continue
        best = unlocked[-1]
        out.append(Decision("set_pm", {"state": s.id, "building": UNIVERSITY, "pm": best, "acceptable": [best]},
                            f"{s.name} 大学 → {gd.pms[best]['name'].get('zh', best)}（创新更高）"))
    return out[:8]
