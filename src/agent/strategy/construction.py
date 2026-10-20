"""建造：每月往政府建造队列里补几个项目。

依据：
- 建造力每周按队列顺序分配，每个项目每周最多拿到「最大周进度」，多余的给下一个；
  闲置的建造力白白浪费，工资照付（wiki Construction）→ 队列要一直有活；
- 社区共识：先铺建造部门、让木材与布料便宜，再工具 → 铁 → 煤 → 钢；
- 建什么：每级每周利润 = 产出 − 投入（本国市场价）− 工资（雇员 / 1000 × 工资率 × 职业混合），
  除以建造点数（GetRequiredConstruction）= 每点建造力的回报。生产方式按同样的利润挑。

修正：
- 劳动力：州里可招的人（失业 + 自给农民）不够 labor_levels 级的雇员就不建 —— 偏远小州工资低、账面利润高，
  但根本招不到人；
- 未并入（unincorporated）的州建造效率低（wiki：普通 −20%、工业 −30%~−50%），打折；与市场不连通的州不建；
- 工资：州里已有同种建筑时用它自己的工资率（农场工资比工厂低得多），否则用州中位数；
- 基础设施超用、同类建筑已经招不满人、产品已经供过于求（市场价低于基准价太多）都打折；
- 同一建筑这个月排过一次后再排打折（价格会被自己压下去）。
"""

from __future__ import annotations

from statistics import median

from agent.gamedata import GameData
from agent.observe import Snapshot, StateRow
from agent.strategy import economy
from agent.strategy.config import Decision, cfg

SECTOR = "building_construction_sector"
ADMIN = "building_government_administration"


def _wage_rates(snap: Snapshot) -> tuple[dict[int, float], float]:
    """各州（已建成的非自给 / 非政府建筑）工资率的中位数，以及全国中位数。"""
    per_state: dict[int, float] = {}
    all_rates: list[float] = []
    for s in snap.states:
        rates = [b.wage_rate for k, b in s.buildings.items()
                 if b.levels > 0 and b.wage_rate and "subsistence" not in k and k not in (ADMIN, "building_barrack")]
        if rates:
            per_state[s.id] = median(rates)
            all_rates += rates
    return per_state, median(all_rates) if all_rates else 100.0


def _prices(gd: GameData, snap: Snapshot) -> dict[str, float]:
    base = gd.base_prices()
    return {g: (snap.prices.get(g, {}).get("price") or base.get(g, 0.0)) for g in base}


def _queued(snap: Snapshot, key: str) -> int:
    return sum(s.buildings[key].queued for s in snap.states if key in s.buildings)


def slots(snap: Snapshot) -> int:
    """本月最多新排几个政府项目。"""
    c = cfg()["construction"]
    queue = int(snap.country.get("queue_government") or 0)
    cap = snap.country.get("construction") or 0.0
    used = snap.country.get("construction_used") or 0.0
    n = max(0, c["min_queue"] + 1 - queue)
    if cap and used < cap * 0.95:
        n = max(n, 2)
    n = min(n, c["max_new_per_month"])
    balance = snap.country.get("balance") or 0.0
    money = snap.country.get("money") or 0.0
    if balance < 0:
        # 赤字时：国库撑得住才继续排，且最多一个
        if money < -balance * cfg()["budget"]["deficit_weeks"]:
            return 0
        n = min(n, 1)
    return n


def _best_state(snap: Snapshot, key: str) -> StateRow | None:
    """人口最多、且能建这种建筑的州（建造部门、行政机构用）。"""
    ok = [s for s in snap.states if key in s.buildings and s.buildings[key].can_queue]
    return max(ok, key=lambda s: s.population or 0) if ok else None


def candidates(gd: GameData, snap: Snapshot, researched: set[str], costs: dict[str, float]) -> list[Decision]:
    """按优先级排好的建造候选（比 slots 多给几个备选，执行时可能有失败的）。"""
    c = cfg()["construction"]
    n = slots(snap)
    if n <= 0:
        return []
    out: list[Decision] = []

    money = snap.country.get("money") or 0.0
    expenses = snap.country.get("expenses") or 0.0
    balance = snap.country.get("balance") or 0.0
    if _queued(snap, SECTOR) == 0 and (balance > 0 or money > expenses * c["construction_sector_reserve_weeks"]):
        s = _best_state(snap, SECTOR)
        if s:
            out.append(Decision("build", {"state": s.id, "building": SECTOR},
                                f"扩建造部门（{s.name}，人口最多）", score=1e9))
    if (snap.country.get("tax_waste") or 0.0) > c["tax_waste_admin"] and _queued(snap, ADMIN) == 0:
        s = _best_state(snap, ADMIN)
        if s:
            out.append(Decision("build", {"state": s.id, "building": ADMIN},
                                f"税收浪费 {snap.country['tax_waste']:.0%}，补官僚（{s.name}）", score=1e8))

    prices = _prices(gd, snap)
    base = gd.base_prices()
    laws = {l.key for l in snap.laws.values() if l.key}
    wages, wage_all = _wage_rates(snap)
    skip = set(cfg()["skip_buildings"])
    econ_cache: dict[tuple[str, int], economy.BuildingEconomics] = {}
    scored: list[Decision] = []
    for s in snap.states:
        if s.isolated:
            continue
        labor = s.labor
        for key, row in s.buildings.items():
            if not row.can_queue or key in skip or key not in gd.buildings:
                continue
            rate = row.wage_rate or wages.get(s.id, wage_all)
            wage = rate * c["wage_mix"] / 1000.0
            ck = (key, round(rate))
            if ck not in econ_cache:
                econ_cache[ck] = economy.building_economics(gd, key, prices, researched, laws, wage, costs.get(key))
            econ = econ_cache[ck]
            score = econ.profit_per_construction
            if not score or score <= 0:
                continue
            notes = []
            if labor < econ.workers * c["labor_levels"]:
                continue
            if not s.incorporated:
                score *= c["unincorporated_penalty"]
                notes.append("未并入")
            if s.infrastructure is not None and s.infrastructure_usage is not None \
                    and s.infrastructure_usage > s.infrastructure:
                score *= c["infra_overuse_penalty"]
                notes.append("基础设施超用")
            if row.levels > 0 and row.employment is not None and row.employment < c["low_employment"]:
                score *= c["low_employment_penalty"]
                notes.append(f"招工 {row.employment:.0%}")
            glut = [g for g in econ.outputs if base.get(g) and prices.get(g, 0) < base[g] * c["oversupply_ratio"]]
            if glut:
                score *= c["oversupply_penalty"]
                notes.append("供过于求：" + ",".join(glut))
            why = f"{s.name} 每级周利润 {econ.profit:,.0f}，{econ.construction:.0f} 点" + \
                  (f"（{'；'.join(notes)}）" if notes else "")
            scored.append(Decision("build", {"state": s.id, "building": key}, why, score))

    # 贪心：同一建筑每月最多 per_type_per_month 级，每排一级后续打折
    taken: dict[str, int] = {}
    pool = scored[:]
    picked: list[Decision] = []
    while pool and len(picked) < n * 3:
        pool.sort(key=lambda d: d.score * c["repeat_penalty"] ** taken.get(d.args["building"], 0), reverse=True)
        d = pool.pop(0)
        k = d.args["building"]
        if taken.get(k, 0) >= c["per_type_per_month"]:
            continue
        taken[k] = taken.get(k, 0) + 1
        picked.append(d)
    return out + picked
