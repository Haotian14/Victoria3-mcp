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
FINANCIAL = "building_financial_district"
RAILWAY = "building_railway"
PORT = "building_port"
TRADE_CENTER = "building_trade_center"


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
    rush = c.get("construction_rush") or {}
    rush_on = False
    if rush.get("enabled"):
        sector_states = [s for s in snap.states if SECTOR in s.buildings]
        if sector_states:
            have_done = sum(s.buildings[SECTOR].levels for s in sector_states)
            rush_on = have_done < int(rush.get("until_levels", 0) or 0)
    queue = int(snap.country.get("queue_government") or 0)
    cap = snap.country.get("construction") or 0.0
    used = snap.country.get("construction_used") or 0.0
    n = max(0, c["min_queue"] + 1 - queue)
    if cap and used < cap * 0.95:
        n = max(n, 2)
    # 建造力闲置说明队列空了：多排几个，别让 100+ 点建造力白拿工资
    if cap and used < cap * 0.80:
        n = max(n, 6)
    if cap and used < cap * 0.60:
        n = max(n, 8)
    n = min(n, c["max_new_per_month"])
    # 国库超过储备上限的一半：钱闲着没用，多排（储备软上限以上的结余收益递减）
    limit = snap.country.get("gold_limit") or 0.0
    if limit and (snap.country.get("money") or 0.0) > limit * 0.5:
        n = max(n, c["max_new_rich"])
    balance = snap.country.get("balance") or 0.0
    money = snap.country.get("money") or 0.0
    credit = snap.country.get("credit_left") or 0.0
    broke_but_credit = money <= 0 and balance <= 0 and credit > 0
    if money <= 0 and balance <= 0 and not broke_but_credit:
        return 0                     # 借债且无信用：先别再加开支
    if broke_but_credit:
        # 破产但还有信用：至少排 2 个自偿项目，别让建造力闲置
        n = max(n, int(c.get("broke_min_slots", 2)))
    if balance < 0:
        # 赤字时：国库撑得住才继续排；国库很厚且赤字很小则允许正常扩建
        if money < -balance * cfg()["budget"]["deficit_weeks"] and not broke_but_credit:
            return 0
        expenses = snap.country.get("expenses") or 0.0
        income = snap.country.get("income") or 1.0
        deep = (expenses and money > expenses * float(c.get("deficit_construction_weeks", 26))
                and balance > -income * float(c.get("deficit_construction_ratio", 0.03)))
        if not deep and not broke_but_credit:
            n = min(n, 1)
    if queue > int(c.get("hard_stop", 45)):
        # 冲刺期队列长是正常的：建造部门优先，继续排；否则先清队列
        return int(rush.get("max_parallel", 8)) if rush_on else 0
    if queue > int(c.get("max_queue", 30)):
        n = min(n, 2)                # 队列偏长：只留建造部门/食品等最高优先
    if rush_on:
        n = max(n, int(rush.get("max_parallel", 8)))
    return n


def _best_state(snap: Snapshot, key: str) -> StateRow | None:
    """人口最多、且能建这种建筑的州（建造部门、行政机构用）。"""
    ok = [s for s in snap.states if key in s.buildings and s.buildings[key].can_queue]
    return max(ok, key=lambda s: s.population or 0) if ok else None


def _take_slots(out: list[Decision], picked: list[Decision], n: int,
                keys: set[str], min_slots: int) -> tuple[list[Decision], list[Decision]]:
    """从 picked 里取出最多 min_slots 个 keys 类项目（不插入）。"""
    if n <= 0 or not keys:
        return [], picked
    have = sum(1 for d in out[:n] if d.args.get("building") in keys)
    need = int(min_slots) - have
    if need <= 0:
        return [], picked
    movers = [d for d in picked if d.args.get("building") in keys][:need]
    if not movers:
        return [], picked
    picked = [d for d in picked if not any(d is m for m in movers)]
    return movers, picked


def _insert_required(out: list[Decision], required: list[Decision], n: int) -> list[Decision]:
    """把保底项目一起插到前 n 个槽位；一起插才不会互相把对方挤出 n。"""
    if not required:
        return out
    at = max(0, min(len(out), n - len(required)))
    for d in reversed(required):
        out.insert(at, d)
    return out


def _ensure_slots(out: list[Decision], picked: list[Decision], n: int,
                  keys: set[str], min_slots: int) -> tuple[list[Decision], list[Decision]]:
    """把 picked 里最多 min_slots 个 keys 类项目提到前 n 个槽位。"""
    movers, picked = _take_slots(out, picked, n, keys, min_slots)
    return _insert_required(out, movers, n), picked


def _consumer_keys(snap: Snapshot) -> set[str]:
    c = cfg()["construction"].get("sol_recovery") or {}
    if not c.get("enabled"):
        return set()
    sol = snap.country.get("sol")
    if sol is None or float(sol) >= float(c.get("sol_below", 8.0)):
        return set()
    return set(c.get("buildings") or ())


def _input_keys(snap: Snapshot) -> set[str]:
    c = cfg()["construction"].get("input_recovery") or {}
    if not c.get("enabled"):
        return set()
    keys: set[str] = set()
    trigger = float(c.get("trigger_ratio", 1.5))
    for good, buildings in (c.get("goods") or {}).items():
        if _buy_sell_ratio(snap, good) >= trigger:
            keys.update(buildings)
    return keys


def _ensure_consumer_slots(out: list[Decision], picked: list[Decision], n: int,
                           snap: Snapshot) -> tuple[list[Decision], list[Decision]]:
    """SoL 低时保证前 n 个建造槽里有消费品项目。

    UP 1840 后靠纺织/家具/食品/牧场把 SoL 从 7.9 拉回 9.5；我们的 plan 里金融区、铁路、
    港口、大学都排在普通工厂前面，槽位一满就轮不到消费品。这里只做“保底 2 个槽”，
    不改变其余排序；picked 里没有可建消费品时什么也不做。
    """
    keys = _consumer_keys(snap)
    if not keys:
        return out, picked
    c = cfg()["construction"].get("sol_recovery") or {}
    return _ensure_slots(out, picked, n, keys, int(c.get("min_slots", 2)))


def _ensure_input_slots(out: list[Decision], picked: list[Decision], n: int,
                        snap: Snapshot) -> tuple[list[Decision], list[Decision]]:
    """铁/工具/煤/木材短缺时，保证前 n 个槽位里有上游项目。

    建造部门再高，缺铁/工具时实际建造力也上不去（UP 1842-12 从 300 掉到 199/296）。
    """
    keys = _input_keys(snap)
    if not keys:
        return out, picked
    c = cfg()["construction"].get("input_recovery") or {}
    return _ensure_slots(out, picked, n, keys, int(c.get("min_slots", 2)))


def _ensure_recovery_slots(out: list[Decision], picked: list[Decision], n: int,
                           snap: Snapshot) -> tuple[list[Decision], list[Decision]]:
    """同时保底上游 + 消费品；两类一起插，避免后一类把前一类挤出前 n 个槽。"""
    required: list[Decision] = []
    input_cfg = cfg()["construction"].get("input_recovery") or {}
    if input_cfg.get("enabled"):
        movers, picked = _take_slots(out, picked, n, _input_keys(snap),
                                     int(input_cfg.get("min_slots", 2)))
        required += movers
    consumer_cfg = cfg()["construction"].get("sol_recovery") or {}
    if consumer_cfg.get("enabled"):
        movers, picked = _take_slots(out, picked, n, _consumer_keys(snap),
                                     int(consumer_cfg.get("min_slots", 2)))
        required += movers
    return _insert_required(out, required, n), picked


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


def steel_frame_multiplier(c: dict, researched: set[str], outputs: list[str]) -> float:
    """攻略：切钢框架前先扩玻璃/钢/工具；触发科技研究后对这些产出的建筑加权。"""
    pre = c.get("steel_frame_prebuild") or {}
    if pre and any(t in researched for t in pre.get("trigger_techs", ())) \
            and set(outputs) & set(pre.get("goods", ())):
        return float(pre.get("multiplier", 1.5))
    return 1.0


def university_target(snap: Snapshot, uni: dict) -> int:
    """攻略：大学先吃满创新上限（约 23 所 / 15% 识字率），识字率升到 40% 约需 60 所；
    1860 年后国库充足再堆到 100 所吃 20% 效率的科技扩散。"""
    target = int(uni.get("target_levels") or 0)
    if not target:
        return 0
    if uni.get("dynamic"):
        literacy = snap.country.get("literacy") or 0.0
        target = max(int(uni.get("min_levels", target)),
                     int(literacy * 100 * float(uni.get("per_literacy", 1.5))))
    late_year = int(uni.get("late_after_year", 0) or 0)
    if late_year and snap.date.year >= late_year:
        limit = snap.country.get("gold_limit") or 0.0
        money = snap.country.get("money") or 0.0
        if limit and money > limit * float(uni.get("late_reserve_ratio", 1.5)):
            target = max(target, int(uni.get("late_target_levels", target)))
    return target


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
    sector_states = [s for s in snap.states if SECTOR in s.buildings]
    have = sum(s.buildings[SECTOR].levels for s in sector_states)
    have_total = sum(s.buildings[SECTOR].levels + s.buildings[SECTOR].queued for s in sector_states)
    rush = c.get("construction_rush") or {}
    rush_on = bool(rush.get("enabled") and sector_states
                   and have < int(rush.get("until_levels", 0) or 0))
    share = c["sector_budget_share"]
    if rush_on:
        share = max(share, float(rush.get("budget_share", share)))
    elif have >= int(c.get("late_after_levels", 0) or 0):
        # 攻略：60 级之后继续扩到 100 级，用更高收入份额；钢框架后 60 级即可到 300+ 建造力
        share = max(share, float(c.get("sector_budget_share_late", share)))
    limit = snap.country.get("gold_limit") or 0.0
    max_levels = int(c.get("construction_sector_max_levels") or 0)
    if limit and money > limit * c.get("sector_rich_reserve_ratio", 1.0):
        share = c.get("sector_budget_share_rich", share)   # 国库超金储备上限：钱闲着，多投建造
    # 收尾窗口：离 100 级只差几级、国库又够厚时，允许用 45% 份额把最后几级建完，
    # 否则 income × 30% 的 cap_levels 会把建造部门卡在 90 多级。
    window = int(c.get("sector_completion_window", 0))
    reserve_weeks = float(c.get("sector_completion_reserve_weeks",
                                c.get("deficit_construction_weeks", 26)))
    if (max_levels and 0 < max_levels - have <= window and expenses
            and money > expenses * reserve_weeks
            and balance > -income * float(c.get("sector_max_deficit_ratio", 0.03))):
        share = max(share, c.get("sector_budget_share_rich", share))
    cap_levels = int(income * share / sector_cost) if sector_cost > 0 else 0
    max_parallel = int(c["construction_sector_max_parallel"])
    if rush_on:
        max_parallel = max(max_parallel, int(rush.get("max_parallel", max_parallel)))
    want = min(max_parallel, cap_levels - have)
    if max_levels:
        # 目标已改为人均 GDP/SoL：建造部门到 100 级（210 建造力）就停，不再吃收入
        want = min(want, max_levels - have)
    # 国库充足时允许小赤字扩建：190 级卡住就是“结余必须 >5% 收入”过严。
    sector_ok = balance > income * c["sector_min_surplus"] or (
        balance > -income * float(c.get("sector_max_deficit_ratio", 0.03)))
    if rush_on:
        sector_ok = sector_ok or balance > -income * float(rush.get("max_deficit_ratio", 0.06))
    inputs_ok = _sector_inputs_ok(prices0, gd.base_prices()) or (
        bool(rush_on) and bool(rush.get("allow_expensive_inputs", True)))
    # 攻略：60 级后继续扩到 100 级，靠铁框架拿 300+ 建造力；国库够厚时允许更大赤字。
    scale = c.get("construction_scale") or {}
    cap_now = snap.country.get("construction") or 0.0
    used_now = snap.country.get("construction_used") or 0.0
    idle = bool(cap_now and used_now < cap_now * float(c.get("idle_used_ratio", 0.75)))
    scale_on = bool(scale.get("enabled") and not rush_on
                    and have >= int(c.get("late_after_levels", 60))
                    and have < int(scale.get("target_levels", 100)))
    if scale_on and idle:
        # 现有建造力都没用满，先别继续扩部门；把资源投到能赚钱的建筑
        scale_on = False
    if not rush_on and idle:
        want = 0
    if scale_on:
        want = min(int(scale.get("max_parallel", 4)),
                   int(scale.get("target_levels", 100)) - have)
        sector_ok = sector_ok or (money > expenses * float(scale.get("reserve_weeks", 26))
                                  and balance > -income * float(scale.get("max_deficit_ratio", 0.08)))
        inputs_ok = True
    if (sector_ok and money > expenses * c["construction_sector_reserve_weeks"]
            and want > 0 and inputs_ok):
        ok = sorted((s for s in snap.states if SECTOR in s.buildings and s.buildings[SECTOR].can_queue
                     and s.incorporated), key=lambda s: -(s.population or 0))
        for i in range(max(0, want)):      # want 已经扣过现有+在建，别再扣一次排队
            if ok:
                s = ok[i % len(ok)]
                out.append(Decision("build", {"state": s.id, "building": SECTOR},
                                    f"扩建造部门（{s.name}；已完成 {have} / 在建 {have_total - have} 级，"
                                    f"上限 {max_levels or '无'}，按收入 {share:.0%} 可养 {cap_levels} 级，每级周成本 "
                                    f"{sector_cost:,.0f}，国库 {money:,.0f}）",
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
                per = int(fs.get("max_per_month", 1))
                if rush_on:
                    per = min(per, int(rush.get("food_max_per_month", 1)))
                for s in pool[:per]:
                    out.append(Decision("build", {"state": s.id, "building": fb},
                                        f"粮食安全：肉短缺（买单/卖单 {ratio:.1f}），优先牧场"
                                        f"（{s.name}；空地 {s.free_arable}）", score=1e6))

    if rush_on:
        # 攻略：冲刺期也要保留进口容量和铁矿，否则铁框架/工具断料。
        tc = profile(snap).get("trade_center") or {}
        target_tc = int(tc.get("target_levels") or 0)
        if rush.get("keep_trade_center", True) and target_tc:
            rows = [(s, s.buildings["building_trade_center"]) for s in snap.states
                    if "building_trade_center" in s.buildings]
            have_tc = sum(row.levels + row.queued for _, row in rows)
            total_target = int(tc.get("target_total_levels") or 0)
            if not total_target or have_tc < total_target:
                pool = [(s, row) for s, row in rows
                        if row.can_queue and row.levels + row.queued < target_tc]
                pool.sort(key=lambda t: (t[1].levels, t[0].population or 0.0), reverse=True)
                for s, row in pool[:1]:
                    out.append(Decision("build", {"state": s.id, "building": "building_trade_center"},
                                        f"冲刺期保留贸易中心（{s.name}；{row.levels}/{target_tc} 级，"
                                        f"全国 {have_tc}/{total_target or '无上限'}）", score=5e7))
        iron_ratio = _buy_sell_ratio(snap, "iron")
        if rush.get("keep_iron_mines", True) and iron_ratio >= float(rush.get("iron_shortage_ratio", 1.5)):
            pool = [s for s in snap.states
                    if "building_iron_mine" in s.buildings and s.buildings["building_iron_mine"].can_queue
                    and s.incorporated and not s.isolated and s.labor >= 5000]
            pool.sort(key=lambda s: s.population or 0.0, reverse=True)
            for s in pool[:int(rush.get("iron_mines_per_month", 2))]:
                out.append(Decision("build", {"state": s.id, "building": "building_iron_mine"},
                                    f"缺铁（买单/卖单 {iron_ratio:.1f}）：冲刺期优先铁矿（{s.name}）",
                                    score=5e6))
        # 攻略：早期每州 1 所大学，提供高薪岗位和识字率，别让冲刺把大学完全挤掉
        uni_spec = profile(snap).get("universities") or {}
        if rush.get("keep_university", True):
            per_state = int(uni_spec.get("max_per_state", 2))
            have_uni = sum(row.levels + row.queued for s in snap.states
                           for key, row in s.buildings.items() if key == UNIVERSITY)
            cap_uni = int(rush.get("university_max_levels", 5))
            if have_uni < cap_uni:
                pool = [s for s in snap.states
                        if UNIVERSITY in s.buildings and s.buildings[UNIVERSITY].can_queue
                        and s.buildings[UNIVERSITY].queued == 0
                        and s.buildings[UNIVERSITY].levels < per_state
                        and s.incorporated and not s.isolated and s.labor >= 500]
                pool.sort(key=lambda s: (s.population or 0.0) / (1 + s.buildings[UNIVERSITY].levels),
                          reverse=True)
                for s in pool[:int(rush.get("university_per_month", 1))]:
                    out.append(Decision("build", {"state": s.id, "building": UNIVERSITY},
                                        f"冲刺期保留大学（{s.name}；全国 {have_uni}/{cap_uni} 级，"
                                        f"识字率 {snap.country.get('literacy') or 0:.0%}）", score=4e6))
        # 冲刺期只排建造部门 + 粮食 + 贸易中心 + 铁矿 + 大学
        return out

    # 官僚：税收浪费说明征税能力不够。按各州缺口补，而不是把行政机构全堆在一个人口最多的州。
    waste = snap.country.get("tax_waste") or 0.0
    admin_states = _admin_states(snap)
    admin_have = sum(row.levels for s in snap.states for k, row in s.buildings.items() if k == ADMIN)
    admin_cap = int(c.get("admin_max_total_levels") or 0)
    # 税收浪费已经很低时，州级“征税能力缺口”只是显示口径，继续堆行政会白占建造槽
    if (not admin_cap or admin_have < admin_cap) and \
            waste > float(c.get("admin_min_tax_waste", 0.02)) and (
            waste > c["tax_waste_admin"] or any(d > 0 for _, d in admin_states)):
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
    total_target = int(tc.get("target_total_levels") or 0)
    if target:
        rows = [(s, s.buildings["building_trade_center"]) for s in snap.states
                if "building_trade_center" in s.buildings]
        have_total = sum(row.levels + row.queued for _, row in rows)
        if not total_target or have_total < total_target:
            pool = [(s, row) for s, row in rows
                    if row.can_queue and row.levels + row.queued < target]
            # 优先把已有大中心补到上限，别每州开一个新坑
            pool.sort(key=lambda t: (t[1].levels, t[0].population or 0.0), reverse=True)
            for s, row in pool[:int(tc.get("max_per_month", 1))]:
                out.append(Decision("build", {"state": s.id, "building": "building_trade_center"},
                                    f"贸易容量饱和：扩贸易中心（{s.name}；{row.levels}/{target} 级，"
                                    f"全国 {have_total}/{total_target or '无上限'}）", score=5e7))

    # 金融区：私人所有每级 +50 资本家，是养大实业家最直接的杠杆。金融区不产出商品，
    # 利润模型看不见它，只能单独排；can_queue=False 的州（地块/城市化不足）自动跳过。
    fd = profile(snap).get("financial_districts") or {}
    fd_target = int(fd.get("target_levels") or 0)
    if fd_target:
        pool = []
        for s in snap.states:
            row = s.buildings.get(FINANCIAL)
            if row is None or not row.can_queue or not s.incorporated or s.isolated:
                continue
            if row.levels + row.queued >= fd_target:
                continue
            pool.append(s)
        pool.sort(key=lambda s: s.population or 0.0, reverse=True)
        for s in pool[:int(fd.get("max_per_month", 2))]:
            row = s.buildings[FINANCIAL]
            out.append(Decision("build", {"state": s.id, "building": FINANCIAL},
                                f"金融区 {row.levels}/{fd_target} 级（{s.name}；私人所有每级 +50 资本家）",
                                score=4e7))

    # 铁路：+20 基础设施是外部性，利润模型看不见；只在 railways 研究后、州基础设施余量
    # 不足时建。快照里没有建造入口（某些版本铁路不在 AccessDevelopmentBuildings）就自动跳过。
    rail = profile(snap).get("railways") or {}
    if rail and "railways" in researched:
        margin = float(rail.get("infra_margin", 20))
        pool = []
        for s in snap.states:
            if not s.incorporated or s.isolated:
                continue
            row = s.buildings.get(RAILWAY)
            if row is None or not row.can_queue:
                continue
            infra, use = s.infrastructure, s.infrastructure_usage
            if infra is None or use is None or use <= infra - margin:
                continue
            pool.append(s)
        pool.sort(key=lambda s: (s.infrastructure_usage or 0.0) - (s.infrastructure or 0.0), reverse=True)
        for s in pool[:int(rail.get("max_per_month", 1))]:
            out.append(Decision("build", {"state": s.id, "building": RAILWAY},
                                f"铁路（{s.name}；基础设施 {s.infrastructure_usage:.0f}/"
                                f"{s.infrastructure:.0f}，余量 <{margin:.0f}）", score=3e7))

    # 港口：贸易容量不足时补，利润低于建造门槛，只在贸易中心接近上限的州排。
    ports = profile(snap).get("ports") or {}
    port_target = int(ports.get("target_levels") or 0)
    if port_target:
        min_tc = int(ports.get("min_trade_center_levels", 45))
        pool = []
        for s in snap.states:
            tc = s.buildings.get(TRADE_CENTER)
            port = s.buildings.get(PORT)
            if tc is None or tc.levels < min_tc or port is None or not port.can_queue:
                continue
            if port.levels + port.queued >= port_target:
                continue
            pool.append(s)
        pool.sort(key=lambda s: s.population or 0.0, reverse=True)
        for s in pool[:int(ports.get("max_per_month", 1))]:
            row = s.buildings[PORT]
            out.append(Decision("build", {"state": s.id, "building": PORT},
                                f"港口 {row.levels}/{port_target} 级（{s.name}；贸易中心 "
                                f"{s.buildings[TRADE_CENTER].levels} 级，容量接近饱和）", score=2e7))

    # 大学：大清攻略的核心是研究速度（识字率低、科技慢）。大学产出创新、不产出商品，
    # 经济账看不见它，只能按攻略单独排。
    uni = profile(snap).get("universities") or {}
    target = university_target(snap, uni)
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
            mult = steel_frame_multiplier(c, researched, econ.outputs)
            if mult > 1.0:
                score *= mult
                notes.append("钢框架前置扩产")
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
    # 优先项目排序：建造部门 → 粮食 → 大学 → 行政 → 贸易中心 → 金融区 → 铁路/港口。
    # 1.13 大学只给创新，但创新决定研究速度；不能被行政/贸易中心挤掉。
    rank = {SECTOR: 0, ADMIN: 3, UNIVERSITY: 2, TRADE_CENTER: 4,
            FINANCIAL: 5, RAILWAY: 6, PORT: 7}
    food_building = (c.get("food_security") or {}).get("building")
    if food_building:
        rank[food_building] = 1
    out.sort(key=lambda d: rank.get(d.args["building"], 9))
    if n > 0:
        # 至少给大学留 1 个槽：否则建造部门 4 级 + 牧场 3 级会把 6-8 个槽吃满，
        # 大学永远排在第 9 位（v4 首轮 12 个月只建了 1 所）。
        ui = next((i for i, d in enumerate(out) if d.args["building"] == UNIVERSITY), None)
        if ui is not None and ui >= n:
            out.insert(n - 1, out.pop(ui))
    out, picked = _ensure_recovery_slots(out, picked, n, snap)
    return out if priority_only else out + picked
