"""自动驾驶：每月一次 —— 读局面 → 策略出计划 → 下发动作（逐条核实）→ 推进到下个月 1 日。

所有决策都在 strategy/ 里，本模块只负责调度、执行、记录：每月的 GDP、国库、建造力、生活水平
记在内存里，一局结束时写一行到 logs/runs.jsonl，用来比较策略改动。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from agent import gamedata, observe
from agent.actions import ActionResult, Actions
from agent.bridge import PLAYER, Bridge, BridgeError, GameError, plain
from agent.game import Clock
from agent.strategy import config as strategy_config
from agent.strategy import diplomacy
from agent.strategy import events as event_policy
from agent.strategy import plan as planner
from agent.strategy import politics
from agent.strategy import research as research_strategy
from agent.strategy.construction import ADMIN, SECTOR, UNIVERSITY
from agent.strategy.config import cfg
from agent.strategy.config import Decision

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
LOG_DIR = os.path.join(ROOT, "logs")

LAW_RETRY_MONTHS = 12
PM_COOLDOWN_MONTHS = 24     # 建筑换过生产方式后这么久不再换（适应期减产 + 防止来回切）
_EVENT_RETRY: dict[int, float] = {}   # 事件 id → 这个时刻之前不再试（答不了就退避，别每秒暂停）

METRICS = ("gdp", "money", "balance", "income", "expenses", "construction", "construction_used",
           "sol", "literacy", "population", "prestige")


@dataclass
class Memory:
    pm_offset: int = 0
    diplo_offset: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)
    counts: dict[str, list[int]] = field(default_factory=dict)   # 动作种类 → [生效, 失败]
    log: list[str] = field(default_factory=list)
    blocked: dict[str, int] = field(default_factory=dict)   # 法律 / 生产方式 → 到第几个月之前不再试

    def tally(self, r: ActionResult, kind: str) -> None:
        ok, bad = self.counts.setdefault(kind, [0, 0])
        noop = r.ok and r.detail.startswith(("已是", "现行"))
        self.counts[kind] = [ok + (r.ok and not noop), bad + (not r.ok)]


def metrics(snap: observe.Snapshot) -> dict[str, Any]:
    out: dict[str, Any] = {"date": str(snap.date)}
    out.update({k: snap.country.get(k) for k in METRICS})
    gdp, pop = out.get("gdp"), out.get("population")
    if gdp and pop:
        out["gdp_per_capita"] = gdp / pop   # 人均 GDP：GDP 增长可能只是人口/建造堆出来的
    return out


def enacting(b: Bridge, snap: observe.Snapshot | None = None) -> str | None:
    try:
        return plain(b.read(f"[{PLAYER}.GetLawBeingEnacted.GetLawType.GetName]")) or None
    except GameError:
        return None


def advise(b: Bridge, mem: Memory | None = None) -> tuple[observe.Snapshot, planner.Plan]:
    """读局面、出计划，不执行。"""
    mem = mem or Memory()
    snap = observe.snapshot(b)
    law = enacting(b)
    # 推行中不能再提法律，也不改组政府：省掉逐条读成功率的几十次往返
    options = [] if law else observe.law_options(b, snap.laws, politics.targets(snap))
    researched = observe.researched(b)
    plan = planner.decide(gamedata.get(), snap, researched, observe.construction_costs(b),
                          law, mem.pm_offset, options)
    # 研究队列：当前研究还在跑、队列空时，把优先表里的下 1–2 项排进去，科技完成后的空窗由游戏接上
    try:
        if snap.researching and not Actions(b).research_queue():
            seen = {snap.researching}
            for d in research_strategy.candidates(gamedata.get(), researched, None,
                                                  strategy_config.tech_priority(snap)):
                t = d.args["tech"]
                if t in seen:
                    continue
                plan.research_queue.append(Decision("queue_research", {"tech": t}, "研究队列补位"))
                seen.add(t)
                if len(plan.research_queue) >= 2:
                    break
    except (GameError, BridgeError):
        pass
    return snap, plan


def handle_events(b: Bridge, mem: Memory, note: Callable[[str], None], tag: str = "",
                  clock: Clock | None = None, keep_running: bool = False) -> int:
    """答掉当前所有待处理事件。接口早就有（Actions.events / choose_event_option），
    以前 runner 从不调用，游戏就按默认选项把它们自动答了。keep_running：答完继续走时间。"""
    try:
        a = Actions(b)
        now = time.time()
        events = [ev for ev in a.events() if _EVENT_RETRY.get(ev["id"], 0.0) <= now]
        if not events:
            return 0
        paused = clock.paused() if clock else True
        if clock and not paused:
            clock.pause()
        try:
            for ev in events:
                idx = event_policy.pick(ev, tag)
                if idx is None:
                    _EVENT_RETRY[ev["id"]] = time.time() + 60
                    continue
                r = a.choose_event_option(ev["id"], idx)
                mem.tally(r, "event")
                note(f"    {r}  ← 事件「{ev['title']}」")
                if not r.ok:
                    _EVENT_RETRY[ev["id"]] = time.time() + 60
        finally:
            if clock and (keep_running or not paused):
                clock.resume()
        return len(events)
    except Exception as exc:                     # 桥接层偶发失败不该让整局停掉
        note(f"    事件处理出错：{type(exc).__name__}: {exc}")
        return 0


def handle_proposals(b: Bridge, mem: Memory, note: Callable[[str], None],
                     snap: observe.Snapshot | None = None) -> int:
    """回复待处理的条约 / 外交行动提议；要挟与拉拢拒绝。"""
    try:
        a = Actions(b)
        answered = 0
        for _ in range(8):
            props = a.proposals()
            if not props:
                break
            p = props[0]
            r = a.answer_proposal(0, diplomacy.accept_proposal(p, snap))
            mem.tally(r, "proposal")
            note(f"    {r}  ← 外交提议「{p.get('name', '')}」（{p.get('actor', '')}）")
            answered += 1
            if not r.ok:
                break
        return answered
    except Exception as exc:
        note(f"    外交提议处理出错：{type(exc).__name__}: {exc}")
        return 0


def handle_diplomacy(b: Bridge, mem: Memory, note: Callable[[str], None],
                     snap: observe.Snapshot | None = None) -> int:
    """每月对一个大国改善关系（俄 / 法 / 普轮流），为保障独立 / 防御同盟铺路。"""
    targets = diplomacy.improve_targets(snap)
    if not targets:
        return 0
    try:
        a = Actions(b)
    except Exception:
        return 0
    n = len(targets)
    for k in range(n):
        tag = targets[(mem.diplo_offset + k) % n]
        try:
            acts = a.diplomatic_actions(tag)
        except Exception:
            continue
        for act in acts:
            if (act.get("action") in ("increase_relations", "improve_relations")
                    and act.get("valid") and not act.get("active")):
                try:
                    r = a.diplomatic_action(tag, act["action"])
                except Exception as exc:
                    note(f"    外交 {tag} 出错：{type(exc).__name__}: {exc}")
                    continue
                mem.tally(r, "diplomacy")
                mem.diplo_offset = (mem.diplo_offset + k + 1) % n
                note(f"    {r}  ← 改善关系（{tag}）")
                return 1
    return 0


def handle_movements(b: Bridge, mem: Memory, note: Callable[[str], None],
                     snap: observe.Snapshot | None = None) -> int:
    """扶持国家档案里指定的政治运动（大清：现代化运动），给教育 / 经济改革提供运动支持。"""
    names = (strategy_config.profile(snap).get("movements") or {}).get("bolster") or []
    if not names:
        return 0
    month = len(mem.history)
    try:
        a = Actions(b)
        ms = {m["name"]: m for m in a.movements()}
        for name in names:
            key = f"movement:{name}"
            if mem.blocked.get(key, -1) > month:
                continue
            m = ms.get(name)
            if not m or m["bolstered"] or m["suppressed"]:
                continue
            # bolster 只提高 pop 吸引力，不直接加 activism；档案默认留空
            r = a.toggle_movement(name, "Bolstering")
            mem.tally(r, "movement")
            note(f"    {r}  ← 扶持运动「{name}」（扩大支持基础）")
            if not r.ok:
                mem.blocked[key] = month + 6
            return 1
    except Exception as exc:
        note(f"    运动处理出错：{type(exc).__name__}: {exc}")
    return 0


def handle_military(b: Bridge, note: Callable[[str], None]) -> int:
    """最小军事姿态：战时军饷 High，和平 Medium。动员/升级只在有战争时由人判断，
    这里不做不可逆动作；Low/VeryLow 的 −50%/−75% 训练速度会让补员永远补不满。"""
    try:
        a = Actions(b)
        wars = a.wars()
        level = "High" if wars else "Medium"
        r = a.set_wage("Military", level)
        if r.ok and not str(r.detail).startswith(("已是", "现行")) and r.before != r.after:
            note(f"    {r}  ← {'战时' if wars else '和平'}军饷 {level}")
            return 1
    except Exception as exc:
        note(f"    军事姿态出错：{type(exc).__name__}: {exc}")
    return 0


def handle_journal(b: Bridge, mem: Memory, note: Callable[[str], None]) -> int:
    """日志按钮 / 决议：只做鸦片相关白名单，且必须在 possible=true 时执行。
    1.13 调研：press_button/take_decision 不检查 possible；通用决议一律不自动按。"""
    month = len(mem.history)
    try:
        a = Actions(b)
        j = a.journal()
        entries = {e["key"]: e for e in j.get("journal_entries", [])}
        e = entries.get("je_opium_obsession")
        if e:
            btn = next((x for x in e.get("buttons", [])
                        if x.get("possible") and x.get("name") == "禁止鸦片贸易"), None)
            if btn:
                key = "journal:ban_opium"
                if mem.blocked.get(key, -1) <= month:
                    r = a.press_button("je_opium_obsession", btn["name"])
                    mem.tally(r, "journal")
                    note(f"    {r}  ← 鸦片危机：禁烟（只按 possible=true 的白名单按钮）")
                    if not r.ok:
                        mem.blocked[key] = month + 6
                    return 1
            return 0
        # JE 不存在：如果仍在禁烟，用白名单决议解除（会移除 opium_ban_authority）
        d = next((x for x in j.get("decisions", [])
                  if x.get("possible") and x.get("name") == "取消鸦片禁令"), None)
        if d:
            key = "journal:unban_opium"
            if mem.blocked.get(key, -1) <= month:
                r = a.take_decision(d["name"])
                mem.tally(r, "journal")
                note(f"    {r}  ← 鸦片 JE 已结束：取消禁令")
                if not r.ok:
                    mem.blocked[key] = month + 6
                return 1
    except Exception as exc:
        note(f"    日志/决议处理出错：{type(exc).__name__}: {exc}")
    return 0


def _promote_queue(a: Actions, note: Callable[[str], None]) -> None:
    """把建造部门 / 粮食建筑的排队项目移到队首（队列常有几百项，队尾永远轮不到）。"""
    c = cfg()["construction"]
    fb = (c.get("food_security") or {}).get("building")
    counts = {SECTOR: 2}
    if fb:
        counts[fb] = 1
    counts["building_logging_camp"] = 2       # 木材是建造部门/建造的瓶颈
    counts["building_trade_center"] = 1       # 每级约 900/周，当前回报最高
    counts["building_railway"] = 1            # 研究后才会有，没有就自动跳过
    budget = int(c.get("priority_build_slots", 7))
    used = 0
    for key, count in counts.items():
        for _ in range(count):
            if used >= budget:
                return
            try:
                q = a.construction_queue()
                idx = next((item["index"] for item in q
                            if item["building"] == key and not item["under_construction"]
                            and item["index"] > 0), None)
                if idx is None:
                    break
                r = a.move_construction(idx, "ToTop")
                if not r.ok:
                    break
                if not r.detail.startswith(("已是", "现行")):
                    note(f"    队列优先：{r.action}")
                    used += 1
            except Exception:
                break


def _clean_queue(a: Actions, note: Callable[[str], None]) -> None:
    """队列超过 max_queue 时，从队尾取消非优先项目（建造部门 / 粮食 / 行政 / 大学保留）。"""
    try:
        c = cfg()["construction"]
        maxq = int(c.get("max_queue", 30))
        q = a.construction_queue()
        if len(q) <= maxq:
            return
        keep = {SECTOR, ADMIN, UNIVERSITY, "building_trade_center", "building_logging_camp",
                "building_railway", "building_port"}
        fb = (c.get("food_security") or {}).get("building")
        if fb:
            keep.add(fb)
        for _ in range(int(c.get("cleanup_per_month", 10))):
            q = a.construction_queue()
            idx = next((item["index"] for item in q
                        if item["building"] not in keep and not item["under_construction"]), None)
            if idx is None:
                break
            r = a.cancel_construction(idx)      # 取消队首最老的低优先项目，别把本月新排的工厂砍掉
            if r.ok and not r.detail.startswith(("已是", "现行")):
                note(f"    {r}")
    except Exception as exc:
        note(f"    队列清理出错：{type(exc).__name__}: {exc}")


def _do(a: Actions, d: Decision, snap: observe.Snapshot) -> ActionResult:
    x = d.args
    if d.kind == "set_tax":
        return a.set_tax(x["level"])
    if d.kind == "set_institution":
        return a.set_institution(x["institution"], x["level"])
    if d.kind == "set_decree":
        return a.set_decree(x["state"], x["decree"])
    if d.kind == "state_action":
        return a.state_action(x["state"], x["cmd"])
    if d.kind == "research":
        return a.research(x["tech"])
    if d.kind == "queue_research":
        return a.queue_research(x["tech"])
    if d.kind == "privatize":
        return a.building_action(x["state"], x["building"], "TogglePrivatization")
    if d.kind == "trade_policy":
        return a.set_trade_policy(x["goods"], x["side"], x["policy"])
    if d.kind == "subsidy":
        return a.building_action(x["state"], x["building"],
                                 "ToggleSubsidiesOn" if x["on"] else "ToggleSubsidiesOff")
    if d.kind == "toggle_consumption_tax":
        return a.toggle_consumption_tax(x["goods"])
    if d.kind == "enact_law":
        return a.enact_law(x["law"], snap)
    if d.kind == "reform_government":
        return a.reform_government(x["members"])
    if d.kind == "build":
        return a.build(x["state"], x["building"], snap)
    if d.kind == "set_pm":
        return a.set_pm(x["state"], x["building"], x["pm"], snap, x.get("acceptable"))
    raise ValueError(f"不认识的决策 {d.kind}")


def execute(b: Bridge, plan: planner.Plan, snap: observe.Snapshot, mem: Memory,
            note: Callable[[str], None]) -> list[ActionResult]:
    a = Actions(b)
    results: list[ActionResult] = []
    _promote_queue(a, note)

    def run(d: Decision) -> ActionResult:
        try:
            r = _do(a, d, snap)
        except GameError as exc:
            r = ActionResult(False, str(d), f"游戏拒绝：{str(exc)[-160:]}")
        mem.tally(r, d.kind)
        results.append(r)
        if not (r.ok and r.detail.startswith(("已是", "现行"))):
            note(f"    {r}  ← {d.why}")
        return r

    month = len(mem.history)
    if plan.tax:
        run(plan.tax)
    for d in plan.institution:                    # 机构投入：不存在（法律没到）就锁一年
        key = f"institution:{d.args['institution']}"
        if mem.blocked.get(key, -1) > month:
            continue
        if not run(d).ok:
            mem.blocked[key] = month + LAW_RETRY_MONTHS
    for d in plan.decree:                         # 州法令：权威力不够就过半年再试
        key = f"decree:{d.args['state']}:{d.args['decree']}"
        if mem.blocked.get(key, -1) > month:
            continue
        if not run(d).ok:
            mem.blocked[key] = month + 6
    for d in plan.incorporate:                    # 并入未合并州：失败就过一年再试
        key = f"incorporate:{d.args['state']}"
        if mem.blocked.get(key, -1) > month:
            continue
        if not run(d).ok:
            mem.blocked[key] = month + LAW_RETRY_MONTHS
    for d in plan.research:                       # 第一条成功即止
        if run(d).ok:
            break
    for d in plan.research_queue:                 # 队列补位：排在当前研究之后
        run(d)
    reformed = False
    if plan.reform and mem.blocked.get("reform", -1) <= month:
        reformed = run(plan.reform).ok
        mem.blocked["reform"] = month + cfg()["politics"]["reform_cooldown_months"]
    for d in ([] if reformed else plan.law):      # 改组后成功率要按新政府重算，下个月再推
        law = d.args["law"]
        if mem.blocked.get(law, -1) > month:
            continue
        r = run(d)
        if r.ok:
            break
        if "不可执行" in r.detail:
            mem.blocked[law] = month + LAW_RETRY_MONTHS   # 缺科技 / 支持不够：过一阵再看
    built = 0
    for d in plan.build:
        if built >= plan.build_slots:
            break
        built += run(d).ok
    for d in plan.pm:
        key = f"{d.args['state']}:{d.args['building']}:{d.args['pm']}"
        cool = f"pm:{d.args['state']}:{d.args['building']}"
        if mem.blocked.get(key, -1) > month or mem.blocked.get(cool, -1) > month:
            continue
        r = run(d)
        if not r.ok:
            mem.blocked[key] = month + LAW_RETRY_MONTHS   # 换不了（不可用 / 没有这个方式）：一年内不再试
        elif r.before != r.after:
            mem.blocked[cool] = month + PM_COOLDOWN_MONTHS
    for d in plan.subsidy:                        # 补贴亏损工业：盈利后取消补贴并私有化
        key = f"subsidy:{d.args['state']}:{d.args['building']}"
        if mem.blocked.get(key, -1) > month:
            continue
        if not run(d).ok:
            mem.blocked[key] = month + LAW_RETRY_MONTHS
    for d in plan.consumption:                    # 消费税：一次开一项，权威力不够就过半年再试
        key = f"consumption:{d.args['goods']}"
        if mem.blocked.get(key, -1) > month:
            continue
        if not run(d).ok:
            mem.blocked[key] = month + 6
    for d in plan.privatize:                      # 私有化：养大实业家（学校法只有他们支持）
        key = f"privatize:{d.args['state']}:{d.args['building']}"
        if mem.blocked.get(key, -1) > month:
            continue
        if not run(d).ok:
            mem.blocked[key] = month + LAW_RETRY_MONTHS
    for d in plan.trade:                          # 关税 / 补贴：缺货零进口关税，过剩进口高关税
        key = f"trade:{d.args['goods']}:{d.args['side']}"
        if mem.blocked.get(key, -1) > month:
            continue
        run(d)
        mem.blocked[key] = month + 4              # 游戏冷却 3 个月 + 7 天：成败都锁 4 个月
    mem.pm_offset += len(plan.pm) or 1
    _clean_queue(a, note)      # 放在建造之后：清理会改变州建筑列表顺序，先清会让本月快照路径失效
    return results


def step(b: Bridge, mem: Memory, note: Callable[[str], None] = lambda s: None) -> dict[str, Any]:
    """本月的决策与执行（不推进时间）。"""
    snap, plan = advise(b, mem)
    m = metrics(snap)
    mem.history.append(m)
    note(f"[{snap.date}] GDP {m['gdp'] or 0:,.0f} 国库 {m['money'] or 0:,.0f} 周结余 {m['balance'] or 0:+,.0f} "
         f"建造力 {m['construction_used'] or 0:.0f}/{m['construction'] or 0:.0f} 生活水平 {m['sol']}")
    tag = str(snap.country.get("tag") or "")
    if handle_events(b, mem, note, tag=tag) > 0:
        snap, plan = advise(b, mem)      # 事件可能改了合法性、法律进度、国库，按新局面临时重算
    handle_proposals(b, mem, note, snap)
    handle_diplomacy(b, mem, note, snap)
    handle_movements(b, mem, note, snap)
    handle_journal(b, mem, note)
    handle_military(b, note)
    results = execute(b, plan, snap, mem, note)
    return {"date": str(snap.date), "metrics": m, "results": [str(r) for r in results]}


def _record(summary: dict[str, Any]) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(os.path.join(LOG_DIR, "runs.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(summary, ensure_ascii=False) + "\n")


def play(b: Bridge, months: int = 12, verbose: Callable[[str], None] | None = None,
         label: str = "", act: bool = True) -> dict[str, Any]:
    """从当前日期起每月决策一次，共 months 个月，结束时写一行 logs/runs.jsonl。
    act=False 是基线：不做任何动作（游戏 AI 不接管玩家国家），只按月记录同样的指标。"""
    mem = Memory()
    clock = Clock(b)
    clock.pause()

    def note(line: str) -> None:
        mem.log.append(line)
        if verbose:
            verbose(line)

    t0 = time.time()
    start = clock.date()
    try:
        tag = plain(b.read(f"[{PLAYER}.GetTagName]") or "")
    except GameError:
        tag = ""
    stopped = f"已走满 {months} 个月"
    for _ in range(months):
        try:
            if act:
                step(b, mem, note)
            else:
                snap = observe.snapshot(b, with_buildings=False)
                mem.history.append(metrics(snap))
                note(f"[{snap.date}] GDP {snap.country.get('gdp') or 0:,.0f}（基线，不干预）")
            if act:
                ticks = {"n": 0}

                def on_tick() -> None:
                    handle_events(b, mem, note, tag=tag, clock=clock, keep_running=True)
                    ticks["n"] += 1
                    if ticks["n"] % 5 == 0:      # 提议不用每秒读
                        handle_proposals(b, mem, note)

                callback = on_tick
            else:
                callback = None
            clock.run_until(clock.date().next_month(), on_tick=callback)
        except Exception as exc:      # 记一笔再停，已走的月份照样记入 runs.jsonl
            stopped = f"出错：{type(exc).__name__}: {exc}"
            note(stopped)
            break
    try:
        mem.history.append(metrics(observe.snapshot(b, with_buildings=False)))
    except Exception:
        pass
    summary = {
        "t": time.strftime("%Y-%m-%d %H:%M:%S"), "label": label or ("strategy" if act else "baseline"),
        "stopped": stopped, "country": observe.country(b)[0],
        "start": str(start), "end": mem.history[-1]["date"] if mem.history else None,
        "months": max(0, len(mem.history) - 1), "seconds": round(time.time() - t0),
        "start_metrics": mem.history[0] if mem.history else None,
        "end_metrics": mem.history[-1] if mem.history else None,
        "actions": mem.counts, "history": mem.history,
    }
    _record(summary)
    summary["log_tail"] = mem.log[-40:]
    return summary
