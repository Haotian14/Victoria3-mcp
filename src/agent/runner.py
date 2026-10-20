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
from agent.bridge import PLAYER, Bridge, GameError, plain
from agent.game import Clock
from agent.strategy import plan as planner
from agent.strategy.config import Decision

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
LOG_DIR = os.path.join(ROOT, "logs")

METRICS = ("gdp", "money", "balance", "income", "expenses", "construction", "construction_used",
           "sol", "literacy", "population", "prestige")


@dataclass
class Memory:
    pm_offset: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)
    counts: dict[str, list[int]] = field(default_factory=dict)   # 动作种类 → [生效, 失败]
    log: list[str] = field(default_factory=list)

    def tally(self, r: ActionResult, kind: str) -> None:
        ok, bad = self.counts.setdefault(kind, [0, 0])
        noop = r.ok and r.detail.startswith(("已是", "现行"))
        self.counts[kind] = [ok + (r.ok and not noop), bad + (not r.ok)]


def metrics(snap: observe.Snapshot) -> dict[str, Any]:
    out: dict[str, Any] = {"date": str(snap.date)}
    out.update({k: snap.country.get(k) for k in METRICS})
    return out


def enacting(b: Bridge) -> str | None:
    try:
        return plain(b.read(f"[{PLAYER}.GetLawBeingEnacted.GetLawType.GetName]")) or None
    except GameError:
        return None


def advise(b: Bridge, mem: Memory | None = None) -> tuple[observe.Snapshot, planner.Plan]:
    """读局面、出计划，不执行。"""
    mem = mem or Memory()
    snap = observe.snapshot(b)
    plan = planner.decide(gamedata.get(), snap, observe.researched(b), observe.construction_costs(b),
                          enacting(b), mem.pm_offset)
    return snap, plan


def _do(a: Actions, d: Decision, snap: observe.Snapshot) -> ActionResult:
    x = d.args
    if d.kind == "set_tax":
        return a.set_tax(x["level"])
    if d.kind == "research":
        return a.research(x["tech"])
    if d.kind == "enact_law":
        return a.enact_law(x["law"], snap)
    if d.kind == "build":
        return a.build(x["state"], x["building"], snap)
    if d.kind == "set_pm":
        return a.set_pm(x["state"], x["building"], x["pm"], snap, x.get("acceptable"))
    raise ValueError(f"不认识的决策 {d.kind}")


def execute(b: Bridge, plan: planner.Plan, snap: observe.Snapshot, mem: Memory,
            note: Callable[[str], None]) -> list[ActionResult]:
    a = Actions(b)
    results: list[ActionResult] = []

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

    if plan.tax:
        run(plan.tax)
    for d in plan.research:                       # 第一条成功即止
        if run(d).ok:
            break
    for d in plan.law:
        if run(d).ok:
            break
    built = 0
    for d in plan.build:
        if built >= plan.build_slots:
            break
        built += run(d).ok
    for d in plan.pm:
        run(d)
    mem.pm_offset += len(plan.pm) or 1
    return results


def step(b: Bridge, mem: Memory, note: Callable[[str], None] = lambda s: None) -> dict[str, Any]:
    """本月的决策与执行（不推进时间）。"""
    snap, plan = advise(b, mem)
    m = metrics(snap)
    mem.history.append(m)
    note(f"[{snap.date}] GDP {m['gdp'] or 0:,.0f} 国库 {m['money'] or 0:,.0f} 周结余 {m['balance'] or 0:+,.0f} "
         f"建造力 {m['construction_used'] or 0:.0f}/{m['construction'] or 0:.0f} 生活水平 {m['sol']}")
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
    stopped = f"已走满 {months} 个月"
    for _ in range(months):
        try:
            if act:
                step(b, mem, note)
            else:
                snap = observe.snapshot(b, with_buildings=False)
                mem.history.append(metrics(snap))
                note(f"[{snap.date}] GDP {snap.country.get('gdp') or 0:,.0f}（基线，不干预）")
            clock.run_until(clock.date().next_month())
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
