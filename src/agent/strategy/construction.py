"""建造：每月往政府建造队列里补几个项目。

依据：
- 建造力每周按队列顺序分配，每个项目每周最多拿到「最大周进度」，多余的给下一个；
  闲置的建造力白白浪费，工资照付（wiki Construction）→ 队列要一直有活；
- 社区共识：先铺建造部门、让木材与布料便宜，再工具 → 铁 → 煤 → 钢；
- 建什么：每级每周利润 = 产出 − 投入（本国市场价）− 工资（雇员 / 10000 × 工资率 × 职业混合），
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
from agent.strategy.config import Decision, cfg, profile

SECTOR = "building_construction_sector"
ADMIN = "building_government_administration"
UNIVERSITY = "building_university"


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
    # 国库超过储备上限的一半：钱闲着没用，多排（储备软上限以上的结余收益递减）
    limit = snap.country.get("gold_limit") or 0.0
    if limit and (snap.country.get("money") or 0.0) > limit * 0.5:
        n = max(n, c["max_new_rich"])
    balance = snap.country.get("balance") or 0.0
    money = snap.country.get("money") or 0.0
    if money <= 0 and balance <= 0:
        return 0                     # 已在借债：先别再加开支
    if balance < 0:
        # 赤字时：国库撑得住才继续排；国库很厚且赤字很小则允许正常扩建
        if money < -balance * cfg()["budget"]["deficit_weeks"]:
            return 0
        expenses = snap.country.get("expenses") or 0.0
        income = snap.country.get("income") or 1.0
        deep = (expenses and money > expenses * float(c.get("deficit_construction_weeks", 26))
                and balance > -income * float(c.get("deficit_construction_ratio", 0.03)))
        if not deep:
            n = min(n, 1)
    if queue > int(c.get("hard_stop", 45)):
        return 0                     # 队列已积压多年：先清队列，不再新排
    if queue > int(c.get("max_queue", 30)):
        n = min(n, 2)                # 队列偏长：只留建造部门/食品等最高优先
    return n


def _best_state(snap: Snapshot, key: str) -> StateRow | None:
    """人口最多、且能建这种建筑的州（建造部门、行政机构用）。"""
    ok = [s for s in snap.states if key in s.buildings and s.buildings[key].can_queue]
    return max(ok, key=lambda s: s.population or 0) if ok else None


def _sector_inputs_ok(prices: dict[str, float], base: dict[str, float]) -> bool:
    """建造部门吃木材与布料：这两种贵了就先别扩，等原材料产业追上（社区共识：木材与布料要便宜）。"""
    c = cfg()["construction"]
    ratio = c.get("sector_input_max_price_ratio") or 0.0
    if ratio <= 0:
        return True
    return all(not base.get(g) or prices.get(g, 0.0) <= base[g] * ratio
               for g in c.get("sector_inputs", ()))


def _admin_states(snap: Snapshot) -> list[tuple[StateRow, float]]:
    """按「征税能力缺口」（已用 − 可用）从大到小排；缺口都为 0 时按人口排。
    大清 1836 的税收浪费接近一半，缺口集中在人口大州，不能可着一个州堆行政机构。"""
    rows: list[tuple[StateRow, float]] = []
    for s in snap.states:
        if not s.incorporated:
            continue
        row = s.buildings.get(ADMIN)
        if row is None or not row.can_queue:
            continue
        deficit = 0.0
        if s.tax_capacity is not None and s.tax_capacity_usage is not None:
            deficit = max(0.0, s.tax_capacity_usage - s.tax_capacity)
        rows.append((s, deficit))
    rows.sort(key=lambda t: (t[1], t[0].population or 0.0), reverse=True)
    return rows


def _buy_sell_ratio(snap: Snapshot, good: str) -> float:
    p = snap.prices.get(good) or {}
    buy = p.get("buy") or 0.0
    sell = p.get("sell") or 0.0
    return buy / max(sell, 1.0) if buy > 0 else 0.0


def _food_short(snap: Snapshot, c: dict) -> bool:
    fs = c.get("food_security") or {}
    trigger = float(fs.get("trigger_ratio", 1.5))
    return any(_buy_sell_ratio(snap, g) > trigger for g in fs.get("goods", ()))


def candidates(gd: GameData, snap: Snapshot, researched: set[str], costs: dict[str, float]) -> list[Decision]:
    """按优先级排好的建造候选（比 slots 多给几个备选，执行时可能有失败的）。"""
    c = cfg()["construction"]
    n = slots(snap)
    priority_only = n <= 0          # 队列积压：只排部门/食品/行政/大学/贸易中心，不排普通工厂
    out: list[Decision] = []
    fs = c.get("food_security") or {}
    food_short = _food_short(snap, c)

    money = snap.country.get("money") or 0.0
    expenses = snap.country.get("expenses") or 0.0
    balance = snap.country.get("balance") or 0.0
    # 建造部门：每级每周要吃 75 木 + 25 布（木制建筑）外加工资，建多了预算撑不住（普鲁士自测：
    # 8 个月加了 16 级，开支从 6.5 万涨到 14.5 万，国库见底、借债、GDP 反降）。
    # 所以按收入定上限：现有 + 在建级数 × 每级周成本 ≤ 收入 × sector_budget_share；结余为正才加。
    prices0 = _prices(gd, snap)
    wages0, wage_all0 = _wage_rates(snap)
    sector_cost = -economy.building_economics(gd, SECTOR, prices0, researched,
                                              {l.key for l in snap.laws.values() if l.key},
                                              wage_all0 * c["wage_mix"] / 10000.0).profit
    income = snap.country.get("income") or 0.0
    have = sum(s.buildings[SECTOR].levels + s.buildings[SECTOR].queued for s in snap.states if SECTOR in s.buildings)
    share = c["sector_budget_share"]
    limit = snap.country.get("gold_limit") or 0.0
    if limit and money > limit * c.get("sector_rich_reserve_ratio", 1.0):
        share = c.get("sector_budget_share_rich", share)   # 国库超金储备上限：钱闲着，多投建造
    cap_levels = int(income * share / sector_cost) if sector_cost > 0 else 0
    want = min(c["construction_sector_max_parallel"], cap_levels - have)
    # 国库充足时允许小赤字扩建：190 级卡住就是“结余必须 >5% 收入”过严。
    sector_ok = balance > income * c["sector_min_surplus"] or (
        balance > -income * float(c.get("sector_max_deficit_ratio", 0.03)))
    if (sector_ok and money > expenses * c["construction_sector_reserve_weeks"]
            and want > 0 and _sector_inputs_ok(prices0, gd.base_prices())):
        ok = sorted((s for s in snap.states if SECTOR in s.buildings and s.buildings[SECTOR].can_queue
                     and s.incorporated), key=lambda s: -(s.population or 0))
        for i in range(max(0, want)):      # want 已经扣过现有+在建，别再扣一次排队
            if ok:
                s = ok[i % len(ok)]
                out.append(Decision("build", {"state": s.id, "building": SECTOR},
                                    f"扩建造部门（{s.name}；已有 {have} 级，按收入 {share:.0%} 可养 "
                                    f"{cap_levels} 级，每级周成本 {sector_cost:,.0f}，国库 {money:,.0f}）",
                                    score=1e9 - i))
    # 粮食安全：肉短缺时强制排牧场。经济账对牧场偏悲观（工资高、账面亏损），
    # 但缺肉会直接拖生活水平，值得用建造力换。
    if food_short:
        fb = fs.get("building")
        ratio = max((_buy_sell_ratio(snap, g) for g in fs.get("goods", ())), default=0.0)
        if fb and fb in gd.buildings:
            have_food = sum(row.levels + row.queued for s in snap.states
                            for k, row in s.buildings.items() if k == fb)
            if have_food < int(fs.get("max_levels", 80)):     # 别无限往队列里塞
                pool = [s for s in snap.states
                        if fb in s.buildings and s.buildings[fb].can_queue
                        and s.incorporated and not s.isolated
                        and (s.free_arable or 0) > 0
                        and s.labor >= float(fs.get("min_labor", 5000))]
                pool.sort(key=lambda s: (s.free_arable or 0) * (s.population or 0), reverse=True)
                for s in pool[:int(fs.get("max_per_month", 1))]:
                    out.append(Decision("build", {"state": s.id, "building": fb},
                                        f"粮食安全：肉短缺（买单/卖单 {ratio:.1f}），优先牧场"
                                        f"（{s.name}；空地 {s.free_arable}）", score=1e6))

    # 官僚：税收浪费说明征税能力不够。按各州缺口补，而不是把行政机构全堆在一个人口最多的州。
    waste = snap.country.get("tax_waste") or 0.0
    admin_states = _admin_states(snap)
    if waste > c["tax_waste_admin"] or any(d > 0 for _, d in admin_states):
        added = 0
        for s, deficit in admin_states:
            if added >= int(c.get("admin_max_per_month", 1)):
                break
            row = s.buildings.get(ADMIN)
            if row is None or row.queued > 0:
                continue
            out.append(Decision("build", {"state": s.id, "building": ADMIN},
                                f"税收浪费 {waste:.0%}，补官僚（{s.name}；征税能力缺口 {deficit:,.0f}）",
                                score=1e8 - deficit))
            added += 1

    # 贸易中心：1.13 没有手动贸易路线，贸易量由贸易中心自治执行。广州体系下只有广东西部能建，
    # 上限 50 级；342 容量早已饱和，继续调关税的边际收益很低，扩容才是主杠杆。
    tc = profile(snap).get("trade_center") or {}
    target = int(tc.get("target_levels") or 0)
    if target:
        added = 0
        for s in snap.states:
            row = s.buildings.get("building_trade_center")
            if row is None or not row.can_queue or row.levels + row.queued >= target:
                continue
            out.append(Decision("build", {"state": s.id, "building": "building_trade_center"},
                                f"贸易容量饱和：扩贸易中心（{s.name}；{row.levels}/{target} 级）",
                                score=5e7))
            added += 1
            if added >= int(tc.get("max_per_month", 1)):
                break

    # 大学：大清攻略的核心是研究速度（识字率低、科技慢）。大学产出创新、不产出商品，
    # 经济账看不见它，只能按攻略单独排。
    uni = profile(snap).get("universities") or {}
    target = int(uni.get("target_levels") or 0)
    if target > 0:
        have = sum(row.levels + row.queued for s in snap.states
                   for key, row in s.buildings.items() if key == UNIVERSITY)
        if have < target:
            per_state = int(uni.get("max_per_state", 2))
            pool = [s for s in snap.states
                    if UNIVERSITY in s.buildings and s.buildings[UNIVERSITY].can_queue
                    and s.buildings[UNIVERSITY].queued == 0
                    and s.buildings[UNIVERSITY].levels < per_state
                    and s.incorporated and not s.isolated and s.labor >= 500]
            pool.sort(key=lambda s: (s.population or 0.0) / (1 + s.buildings[UNIVERSITY].levels),
                      reverse=True)
            for s in pool[:int(uni.get("max_per_month", 1))]:
                out.append(Decision("build", {"state": s.id, "building": UNIVERSITY},
                                    f"大学 {have}/{target} 级（{s.name}；已有 "
                                    f"{s.buildings[UNIVERSITY].levels} 级，人口 {s.population or 0:,.0f}）",
                                    score=1e7))

    prices = _prices(gd, snap)
    base = gd.base_prices()
    laws = {l.key for l in snap.laws.values() if l.key}
    wages, wage_all = _wage_rates(snap)
    skip = set(cfg()["skip_buildings"])
    prio_goods = profile(snap).get("priority_goods") or {}
    econ_cache: dict[tuple[str, int], economy.BuildingEconomics] = {}
    scored: list[Decision] = []
    for s in snap.states:
        if s.isolated:
            continue
        labor = s.labor
        for key, row in s.buildings.items():
            if not row.can_queue or key in skip or key not in gd.buildings:
                continue
            if s.free_arable is not None and s.free_arable <= 0 and any(
                    x in key for x in ("farm", "plantation", "ranch")):
                continue                                     # 没空地了，别排农业
            rate = row.wage_rate or wages.get(s.id, wage_all)
            wage = rate * c["wage_mix"] / 10000.0
            ck = (key, round(rate))
            if ck not in econ_cache:
                econ_cache[ck] = economy.building_economics(gd, key, prices, researched, laws, wage, costs.get(key))
            econ = econ_cache[ck]
            score = econ.profit_per_construction
            if not score or score < c["min_profit_per_point"]:
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
            # 缺货加分：买单/卖单 > start（肉、木材、铁这类买不到的，价格再高也可能不够）
            start = c.get("shortage_bonus_start", 1.2)
            ratios = {g: _buy_sell_ratio(snap, g) for g in econ.outputs}
            if ratios:
                g, ratio = max(ratios.items(), key=lambda kv: kv[1])
                if ratio > start:
                    mult = min(c.get("shortage_bonus_max", 1.6),
                               1 + (ratio - start) * c.get("shortage_bonus_per_ratio", 0.8))
                    score *= mult
                    notes.append(f"缺货 {g} ×{mult:.1f}（买单/卖单 {ratio:.1f}）")
            hits = [(g, w) for g, w in prio_goods.items() if g in econ.outputs]
            if hits:
                g, w = max(hits, key=lambda kv: kv[1])
                score *= float(w)
                notes.append(f"优先 {g} ×{float(w):.1f}")
            if food_short and key in set(fs.get("cash_crops", ())):
                if fs.get("skip_cash_crops", False):
                    continue
                score *= float(fs.get("penalty", 0.15))
                notes.append("粮食安全降权")
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
    return out if priority_only else out + picked
