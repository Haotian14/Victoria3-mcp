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
from agent.strategy import budget, diplomacy
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
DECISION_WHITELIST = {"举办一场大型博览会"}   # 只在 possible=true 时按；鸦片解禁在 handle_journal 里单独处理
_EVENT_RETRY: dict[int, float] = {}   # 事件 id → 这个时刻之前不再试（答不了就退避，别每秒暂停）

METRICS = ("gdp", "money", "balance", "income", "expenses", "construction", "construction_used",
           "sol", "literacy", "population", "prestige", "max_companies", "num_companies")


@dataclass
class Memory:
    pm_offset: int = 0
    diplo_offset: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)
    counts: dict[str, list[int]] = field(default_factory=dict)   # 动作种类 → [生效, 失败]
    log: list[str] = field(default_factory=list)
    blocked: dict[str, int] = field(default_factory=dict)   # 法律 / 生产方式 → 到第几个月之前不再试
    law_stall: int = 0                  # 连续多少个月没有法律在推 / 可推
    enacting: str | None = None         # 本月开始时的现行立法
    journal_active: dict[str, str] = field(default_factory=dict)   # JE key → 进度签名
    journal_names: dict[str, str] = field(default_factory=dict)    # JE key → 名字
    situation: tuple[str, ...] = field(default_factory=tuple)      # 上个月的“当前形势”推导摘要
    fragile_unity: int | None = None    # 脆弱的统一剩余点数（je_warlord_china 进度条）

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
    out["laws"] = sum(1 for law in snap.laws.values() if law.key)
    igs = {ig.name: ig for ig in snap.igs}
    ind = igs.get("实业家")
    out["industrialists_clout"] = ind.clout if ind else None
    out["government"] = ",".join(ig.name for ig in snap.igs if ig.in_gov)
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
    mem.enacting = law
    # 推行中不能再提法律，也不改组政府：省掉逐条读成功率的几十次往返
    targets = politics.targets(snap)
    if mem.law_stall >= politics.fallback_threshold(snap):
        # 兜底法律不在主路线里；不扩展过滤列表的话 observe 读不到它们，兜底永远是空的。
        targets += strategy_config.fallback_route(snap)
    targets = politics.guard_fragile_unity(targets, mem.fragile_unity)
    options = [] if law else observe.law_options(b, snap.laws, targets)
    researched = observe.researched(b)
    plan = planner.decide(gamedata.get(), snap, researched, observe.construction_costs(b),
                          law, mem.pm_offset, options, law_stall=mem.law_stall)
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
    """外交：先做攻略的主动动作（贸易特选 / 使馆 / 法律承诺 / 赠礼），再轮换改善关系。"""
    targets = diplomacy.improve_targets(snap)
    if not targets:
        return 0
    try:
        a = Actions(b)
    except Exception:
        return 0
    spec = (strategy_config.profile(snap).get("diplomacy") or {}) if snap is not None else {}
    proactive = spec.get("proactive") or {}
    journals = (snap.journal_keys or set()) if snap is not None else set()
    money = (snap.country.get("money") or 0.0) if snap is not None else 0.0
    balance = (snap.country.get("balance") or 0.0) if snap is not None else 0.0
    wants: list[tuple[str, Any]] = []
    if proactive.get("trade_privilege"):
        wants.append(("贸易特选", proactive["trade_privilege"]))
    if proactive.get("embassy") and "je_earn_recognition" in journals:
        wants.append(("建立大使馆", proactive["embassy"]))
    if proactive.get("law_commitment") and not mem.enacting and mem.law_stall >= 6:
        wants.append(("法律承诺", proactive["law_commitment"]))
    if proactive.get("gift") and balance > 0 and money > float(proactive.get("gift_budget", 0)) * 10:
        wants.append(("赠礼", proactive["gift"]))
    n = len(targets)
    for k in range(n):
        tag = targets[(mem.diplo_offset + k) % n]
        try:
            acts = a.diplomatic_actions(tag)
        except Exception:
            continue
        for why, keywords in wants:
            for act in acts:
                if act.get("valid") and not act.get("active") and diplomacy.match_action(act, keywords):
                    try:
                        r = a.diplomatic_action(tag, act["action"])
                    except Exception as exc:
                        note(f"    外交 {tag} {why} 出错：{type(exc).__name__}: {exc}")
                        continue
                    mem.tally(r, "diplomacy")
                    if r.ok:
                        mem.diplo_offset = (mem.diplo_offset + k + 1) % n
                        note(f"    {r}  ← {why}（{tag}）")
                        return 1
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


def handle_subjects(b: Bridge, mem: Memory, note: Callable[[str], None],
                    snap: observe.Snapshot | None = None) -> int:
    """攻略：收朝贡国凑授权。只执行游戏判定 valid 的朝贡/保护国行动，失败锁 6 个月。"""
    spec = (strategy_config.profile(snap).get("diplomacy") or {}) if snap is not None else {}
    targets = spec.get("tributary_targets") or []
    keywords = spec.get("tributary_keywords") or []
    if not targets or not keywords:
        return 0
    month = len(mem.history)
    try:
        a = Actions(b)
    except Exception:
        return 0
    for tag in targets:
        try:
            acts = a.diplomatic_actions(tag)
        except Exception:
            continue
        for act in acts:
            if not (act.get("valid") and not act.get("active") and diplomacy.match_action(act, keywords)):
                continue
            key = f"subject:{tag}:{act['action']}"
            if mem.blocked.get(key, -1) > month:
                continue
            try:
                r = a.diplomatic_action(tag, act["action"])
            except Exception as exc:
                note(f"    朝贡 {tag} 出错：{type(exc).__name__}: {exc}")
                mem.blocked[key] = month + 6
                continue
            mem.tally(r, "subject")
            if r.ok:
                note(f"    {r}  ← 朝贡/保护（{tag}）")
                return 1
            mem.blocked[key] = month + 6
    return 0


def handle_bloc(b: Bridge, mem: Memory, note: Callable[[str], None],
                snap: observe.Snapshot | None = None) -> int:
    """攻略：权力集团原则优先教育/研究。只在已入集团时按名称匹配并升级，失败锁 6 个月。"""
    spec = (strategy_config.profile(snap).get("power_bloc") or {}) if snap is not None else {}
    priority = spec.get("principle_priority") or []
    if not priority:
        return 0
    month = len(mem.history)
    try:
        a = Actions(b)
        info = a.bloc()
    except Exception:
        return 0
    if not info.get("in_bloc"):
        return 0
    principles = info.get("principles") or []
    for kw in priority:
        for i, name in enumerate(principles):
            if kw not in str(name):
                continue
            key = f"bloc:{i}"
            if mem.blocked.get(key, -1) > month:
                continue
            try:
                r = a.upgrade_principle(i)
            except Exception as exc:
                note(f"    集团原则出错：{type(exc).__name__}: {exc}")
                mem.blocked[key] = month + int(spec.get("upgrade_cooldown_months", 6))
                continue
            mem.tally(r, "bloc")
            if r.ok:
                note(f"    {r}  ← 集团原则「{name}」")
                return 1
            mem.blocked[key] = month + int(spec.get("upgrade_cooldown_months", 6))
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


def handle_military(b: Bridge, note: Callable[[str], None],
                    snap: observe.Snapshot | None = None) -> int:
    """军事姿态 + 政府工资。
    - 军队：战时 High，和平 Medium；Low/VeryLow 的 −50%/−75% 训练速度会让补员永远补不满。
    - 政府：攻略前期压 Low 换建造资金；重商主义后回 Medium（避免认可/威望惩罚）。"""
    changed = 0
    try:
        a = Actions(b)
        wars = a.wars()
        broke = bool(snap is not None and (snap.country.get("balance") or 0.0) < 0
                     and (snap.country.get("money") or 0.0) <= (snap.country.get("expenses") or 0.0) * 4)
        wspec = (strategy_config.profile(snap).get("wages") or {}) if snap is not None else {}
        level = "High" if wars else (
            "Low" if broke and wspec.get("military_low_when_broke", True) else "Medium")
        r = a.set_wage("Military", level)
        if r.ok and not str(r.detail).startswith(("已是", "现行")) and r.before != r.after:
            note(f"    {r}  ← {'战时' if wars else '和平'}军饷 {level}")
            changed += 1
        if snap is not None:
            gov = budget.government_wage_level(snap, bool(wars))
            if broke and wspec.get("government_low_when_broke", True):
                gov = "Low"
            rg = a.set_wage("Government", gov)
            if rg.ok and not str(rg.detail).startswith(("已是", "现行")) and rg.before != rg.after:
                note(f"    {rg}  ← 政府工资 {gov}")
                changed += 1
    except Exception as exc:
        note(f"    军事姿态出错：{type(exc).__name__}: {exc}")
    return changed


def _je_signature(e: dict[str, Any]) -> str:
    """进度签名：用于只在进度变化时打一行，而不是每月刷屏。"""
    if e.get("has_progress"):
        return f"{e.get('progress_value')}/{e.get('goal_total')}"
    return "可完成" if e.get("can_complete") else ""


def _je_detail(e: dict[str, Any], snap: observe.Snapshot | None = None) -> str:
    parts: list[str] = []
    if e.get("has_progress"):
        pct = str(e.get("progress_percent") or "")
        try:
            pct = f"{float(pct):.0%}"
        except ValueError:
            pass
        parts.append(f"进度 {e.get('progress_value')}/{e.get('goal_total')}（{pct}）")
    for bar in e.get("bars") or []:
        if bar.get("name"):
            parts.append(f"{bar['name']} {bar.get('value', '')}/{bar.get('max', '')}")
    days = str(e.get("timeout_days") or "")
    if days and days != "0":
        parts.append(f"剩余 {days} 天")
    if e.get("can_complete"):
        parts.append("可完成")
    if e.get("progressing"):
        parts.append("进行中")
    if e["key"] == "je_set_up_paper_import":
        parts.append("需要 paper 进口补贴且价格 ≤1.2×基准")
    elif e["key"] == "je_urbanization_events_2":
        parts.append("农本主义会使其失效")
    elif e["key"] == "je_earn_recognition":
        parts.append("承认后脆弱的统一也会完成")
        if snap is not None:
            econ = snap.laws.get("lawgroup_economic_system")
            if econ and econ.key == "law_traditionalism":
                parts.append("传统主义 −1/月")
            literacy = snap.country.get("literacy") or 0.0
            if literacy < 0.4:
                parts.append(f"识字率 {literacy:.0%} <40%")
    buttons = [x["name"] for x in e.get("buttons", []) if x.get("possible")]
    if buttons:
        parts.append(f"可点按钮 {buttons}")
    return "；".join(parts)


def handle_journal(b: Bridge, mem: Memory, note: Callable[[str], None],
                   snap: observe.Snapshot | None = None) -> int:
    """日志条目：记录新出现 / 进度变化 / 结束的 JE，并只按白名单执行 possible=true 的按钮 / 决议。
    1.13 调研：press_button/take_decision 不检查 possible；通用按钮/决议一律不自动按。"""
    month = len(mem.history)
    try:
        a = Actions(b)
        j = a.journal()
        entries = {e["key"]: e for e in j.get("journal_entries", [])}
        for key, e in entries.items():
            sig = _je_signature(e)
            detail = _je_detail(e, snap)
            if key not in mem.journal_active:
                note(f"    ✓ 日志条目：{e['name']}（{key}）" + (f"；{detail}" if detail else ""))
            elif mem.journal_active[key] != sig:
                note(f"    ✓ 日志条目进展：{e['name']}（{key}）" + (f"；{detail}" if detail else ""))
            mem.journal_names[key] = e["name"]
        for key, name in mem.journal_names.items():
            if key not in entries:
                note(f"    ✓ 日志条目结束：{name}（{key}）")
        mem.journal_active = {key: _je_signature(e) for key, e in entries.items()}
        mem.journal_names = {key: e["name"] for key, e in entries.items()}
        # 脆弱的统一：进度条就是剩余容错点；≤1 时法律路线会跳过权力分配组
        mem.fragile_unity = None
        je = entries.get("je_warlord_china")
        if je:
            for bar in je.get("bars") or []:
                name = str(bar.get("name") or "")
                if any(k in name for k in ("统一", "容错", "失败")):
                    try:
                        mem.fragile_unity = int(float(str(bar.get("value") or "")))
                    except ValueError:
                        pass
                    break

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
        # 其他白名单决议（只在 possible=true 时按）
        for d in j.get("decisions", []):
            if not d.get("possible") or d.get("name") not in DECISION_WHITELIST:
                continue
            key = f"decision:{d['name']}"
            if mem.blocked.get(key, -1) > month:
                continue
            r = a.take_decision(d["name"])
            mem.tally(r, "journal")
            note(f"    {r}  ← 日志决议「{d['name']}」")
            if not r.ok:
                mem.blocked[key] = month + 6
            return 1
    except Exception as exc:
        note(f"    日志/决议处理出错：{type(exc).__name__}: {exc}")
    return 0


def _situation_alerts(snap: observe.Snapshot, mem: Memory) -> tuple[str, ...]:
    """“当前形势”的推导版：游戏面板 TopFrontend.AccessImportantActions 是界面对象，
    桥接层读不到；这里用同一批状态（缺货/过剩/合法性/赤字/SoL/研究/公司槽/饥荒/并入/法律停滞）
    生成一份可操作的摘要。"""
    scored: list[tuple[float, str]] = []
    for g in observe.TRADE_WATCH_GOODS:
        p = snap.prices.get(g) or {}
        buy, sell = float(p.get("buy") or 0.0), float(p.get("sell") or 0.0)
        if not buy and not sell:
            continue
        ratio = buy / max(sell, 1.0)
        price, base = float(p.get("price") or 0.0), float(p.get("base") or 0.0)
        px = price / base if base else 0.0
        if ratio >= 1.5 or (px and px >= 1.3):
            scored.append((ratio + px, f"缺货 {g} {ratio:.1f}/{px:.2f}"))
        elif px and px <= 0.7:
            scored.append((1.0 / px, f"过剩 {g} {px:.2f}"))
    scored.sort(reverse=True)
    alerts = [x[1] for x in scored[:4]]
    leg = snap.country.get("legitimacy") or 0.0
    if leg and leg < 50:
        alerts.append(f"合法性 {leg:.0f}")
    balance = snap.country.get("balance") or 0.0
    money = snap.country.get("money") or 0.0
    if balance < 0 and money < -balance * 30:
        alerts.append(f"赤字 {balance:,.0f}/周")
    sol = snap.country.get("sol") or 0.0
    if sol and sol < 7:
        alerts.append(f"SoL {sol:.2f}")
    if not snap.researching:
        alerts.append("无研究")
    maxc = int(snap.country.get("max_companies") or 0)
    numc = int(snap.country.get("num_companies") or 0)
    if maxc > numc and snap.companies and snap.companies.available:
        alerts.append("公司槽空位")
    famine = sum(1 for s in snap.states if s.famine)
    if famine:
        alerts.append(f"饥荒州 {famine}")
    uninc = sum(1 for s in snap.states if not s.incorporated)
    if uninc:
        alerts.append(f"未并入州 {uninc}")
    if mem.law_stall >= 12:
        alerts.append(f"法律停滞 {mem.law_stall} 月")
    return tuple(alerts)


def handle_situation(snap: observe.Snapshot, mem: Memory, note: Callable[[str], None]) -> None:
    alerts = _situation_alerts(snap, mem)
    if alerts != mem.situation:
        note("    当前形势（推导）：" + ("；".join(alerts) if alerts else "无重要警报"))
        mem.situation = alerts


def _sector_below_cap(snap: observe.Snapshot) -> bool:
    """建造部门是否还没到 100 级（含在建）。到顶后不再优先、并可清理多余队列。"""
    cap = int(cfg()["construction"].get("construction_sector_max_levels") or 0)
    if not cap:
        return True
    have = sum(row.levels + row.queued for s in snap.states
               for k, row in s.buildings.items() if k == SECTOR)
    return have < cap


def _trim_sector(a: Actions, snap: observe.Snapshot, note: Callable[[str], None]) -> None:
    """建造部门到 100 级后，取消多出来的排队项目，把建造力让给消费品/上游/铁路。"""
    c = cfg()["construction"]
    cap = int(c.get("construction_sector_max_levels") or 0)
    if not cap:
        return
    have = sum(row.levels for s in snap.states for k, row in s.buildings.items() if k == SECTOR)
    allowed = max(0, cap - have)
    while True:
        try:
            q = a.construction_queue()
        except Exception:
            return
        items = [i for i, item in enumerate(q)
                 if item["building"] == SECTOR and not item["under_construction"]]
        if len(items) <= allowed:
            return
        r = a.cancel_construction(items[-1])
        if not r.ok:
            return
        if not r.detail.startswith(("已是", "现行")):
            note(f"    建造部门已到 {cap} 级：{r}")


def _promote_queue(a: Actions, note: Callable[[str], None],
                   snap: observe.Snapshot | None = None) -> None:
    """把消费品 / 上游 / 铁路 / 金融区 / 建造部门的排队项目移到队首。"""
    c = cfg()["construction"]
    fb = (c.get("food_security") or {}).get("building")
    counts: dict[str, int] = {}
    if snap is None or _sector_below_cap(snap):
        counts[SECTOR] = 2
    for key, count in (c.get("priority_queue") or {}).items():
        if key.startswith("_"):
            continue
        counts[key] = counts.get(key, 0) + int(count)
    if fb:
        counts[fb] = counts.get(fb, 0) + 1
    counts["building_trade_center"] = counts.get("building_trade_center", 0) + 1
    budget = int(c.get("priority_build_slots", 15))
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


def _clean_queue(a: Actions, note: Callable[[str], None],
                 snap: observe.Snapshot | None = None) -> None:
    """队列超过 max_queue 时，从队尾取消非优先项目（消费品/上游/铁路/行政/大学保留）。"""
    try:
        c = cfg()["construction"]
        maxq = int(c.get("max_queue", 30))
        q = a.construction_queue()
        if len(q) <= maxq:
            return
        keep = {ADMIN, UNIVERSITY, "building_trade_center", "building_logging_camp"}
        keep |= {k for k in (c.get("priority_queue") or {}) if not k.startswith("_")}
        if snap is None or _sector_below_cap(snap):
            keep.add(SECTOR)
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
    if d.kind == "company":
        return a.company(x["key"], x.get("create", True))
    if d.kind == "trade_policy":
        return a.set_trade_policy(x["goods"], x["side"], x["policy"])
    if d.kind == "subsidy":
        return a.building_action(x["state"], x["building"],
                                 "ToggleSubsidiesOn" if x["on"] else "ToggleSubsidiesOff")
    if d.kind == "toggle_consumption_tax":
        return a.toggle_consumption_tax(x["goods"], x.get("on"))
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
    _trim_sector(a, snap, note)
    _promote_queue(a, note, snap)

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
    law_started = False
    for d in ([] if reformed else plan.law):      # 改组后成功率要按新政府重算，下个月再推
        law = d.args["law"]
        if mem.blocked.get(law, -1) > month:
            continue
        r = run(d)
        if r.ok:
            law_started = True
            break
        if "不可执行" in r.detail:
            mem.blocked[law] = month + LAW_RETRY_MONTHS   # 缺科技 / 支持不够：过一阵再看
    # 法律卡死计数：真正开始立法 / 改组成功才清零；计划里有但没执行（冷却/失败）不算
    mem.law_stall = 0 if (mem.enacting or reformed or law_started) else mem.law_stall + 1
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
        r = run(d)
        if not r.ok:
            mem.blocked[key] = month + LAW_RETRY_MONTHS
        elif r.before != r.after:
            mem.blocked[key] = month + 6          # 利润在阈值附近抖动：半年内不来回切
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
    for d in plan.company:                        # 公司：同州 5 级 + 资本家类别
        key = f"company:{d.args['key']}"
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
    _clean_queue(a, note, snap)   # 放在建造之后：清理会改变州建筑列表顺序，先清会让本月快照路径失效
    return results


def law_vanished(prev: str | None, snap: observe.Snapshot) -> bool:
    """上个月在推的法，这个月既不是现行法、也不在推：说明失败/被取消。
    完成的法会变成现行法，仍留在 snap.laws 里，所以不会被误判。"""
    if not prev:
        return False
    return all(law.key != prev for law in snap.laws.values())


def step(b: Bridge, mem: Memory, note: Callable[[str], None] = lambda s: None) -> dict[str, Any]:
    """本月的决策与执行（不推进时间）。"""
    prev_law = mem.enacting
    snap, plan = advise(b, mem)
    m = metrics(snap)
    mem.history.append(m)
    note(f"[{snap.date}] GDP {m['gdp'] or 0:,.0f} 国库 {m['money'] or 0:,.0f} 周结余 {m['balance'] or 0:+,.0f} "
         f"建造力 {m['construction_used'] or 0:.0f}/{m['construction'] or 0:.0f} 生活水平 {m['sol']}")
    tag = str(snap.country.get("tag") or "")
    if handle_events(b, mem, note, tag=tag) > 0:
        snap, plan = advise(b, mem)      # 事件可能改了合法性、法律进度、国库，按新局面临时重算
    if law_vanished(prev_law, snap) and not mem.enacting:
        # 立法失败后不要空转满 6 个月：直接按兜底门槛进入下一轮，下一月就能换法。
        mem.law_stall = max(mem.law_stall, politics.fallback_threshold(snap))
        note(f"    法律 {prev_law} 失败/被取消：下月起启用兜底（{mem.law_stall} 月）")
    if (mem.law_stall == politics.fallback_threshold(snap) and not mem.enacting and not plan.law):
        note(f"    法律兜底已启用（连续 {mem.law_stall} 个月无法律），"
             f"本月没有通过率 ≥{politics.fallback_min_pass(snap):.0%} 的关键法")
    handle_proposals(b, mem, note, snap)
    handle_diplomacy(b, mem, note, snap)
    handle_subjects(b, mem, note, snap)
    handle_bloc(b, mem, note, snap)
    handle_movements(b, mem, note, snap)
    handle_journal(b, mem, note, snap)
    handle_situation(snap, mem, note)
    handle_military(b, note, snap)
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
