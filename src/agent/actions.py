"""玩家动作：税率、研究、法律、建造、生产方式。

全部走界面按钮背后的同一条命令（Execute(...)），与玩家点击等价：法律要走推行流程、
建造进建造队列、研究进研究槽，不直接改游戏状态。每个动作：
1. 前置：IsValid(命令)，不可用时附上游戏给的原因（GetDesc）；
2. 执行；
3. 后验：再读一次，确认真的生效（命令是异步的，下一帧才落地，最多等一小会）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

from agent import gamedata
from agent.bridge import PLAYER, Bridge, GameError, plain
from agent.observe import STATES, TAX_LEVELS, Snapshot

PM_GROUPS = "Building.AccessProductionMethodGroups"
PM_OPTIONS = "ProductionMethodGroup.AccessBuildingProductionMethods(Building.Self)"
LAW_ALTERNATIVES = "Law.GetLawAlternatives"


@dataclass
class ActionResult:
    ok: bool
    action: str
    detail: str = ""
    before: Any = None
    after: Any = None

    def __str__(self) -> str:
        mark = "✓" if self.ok else "✗"
        change = f"（{self.before} → {self.after}）" if self.before != self.after else ""
        return f"{mark} {self.action}{change} {self.detail}".rstrip()


class Actions:
    def __init__(self, bridge: Bridge) -> None:
        self.b = bridge

    # ------------------------------------------------------------ 通用
    def _why_not(self, cmd: str, path=None) -> str:
        try:
            return plain(self.b.read(f"[GetDesc({cmd})]", path))[:200]
        except GameError:
            return ""

    def _run(self, name: str, cmd: str, probe: Callable[[], Any], expect: Callable[[Any], bool],
             path=None, wait: float = 1.5) -> ActionResult:
        before = probe()
        if expect(before):
            return ActionResult(True, name, "已是目标状态", before, before)
        if self.b.read(f"[IsValid({cmd})]", path) != "1":
            return ActionResult(False, name, f"不可执行：{self._why_not(cmd, path) or '游戏判定不可用'}", before, before)
        self.b.exec(f"Execute({cmd})", path)
        after = before
        t0 = time.time()
        while time.time() - t0 < wait:
            after = probe()
            if expect(after):
                return ActionResult(True, name, "", before, after)
            time.sleep(0.1)
        return ActionResult(False, name, "已执行但没看到生效", before, after)

    # ------------------------------------------------------------ 税率
    def set_tax(self, level: str) -> ActionResult:
        """level 取 VeryLow / Low / Medium / High / VeryHigh。"""
        if level not in TAX_LEVELS:
            raise ValueError(f"税级只能取 {TAX_LEVELS}")

        def probe():
            vals = self.b.read_many([f"IsValid({PLAYER}.SetTaxLevel{t})" for t in TAX_LEVELS])
            invalid = [t for t, v in zip(TAX_LEVELS, vals) if v == "0"]
            return invalid[0] if len(invalid) == 1 else None

        cmd = f"{PLAYER}.SetTaxLevel{level}"
        before = probe()
        if before == level:
            return ActionResult(True, f"税率 {level}", "已是目标状态", before, before)
        self.b.exec(f"Execute({cmd})")
        after = before
        for _ in range(15):
            after = probe()
            if after == level:
                return ActionResult(True, f"税率 {level}", "", before, after)
            time.sleep(0.1)
        return ActionResult(False, f"税率 {level}", "已执行但没看到生效", before, after)

    # ------------------------------------------------------------ 研究
    def research(self, tech: str) -> ActionResult:
        t = f"GetTechnology('{tech}')"

        def probe():
            vals = self.b.read_many([f"{t}.IsResearching({PLAYER}.Self)", f"{t}.HasResearchedTech({PLAYER}.Self)"])
            return "研究中" if vals[0] == "1" else "已完成" if vals[1] == "1" else "未研究"

        return self._run(f"研究 {tech}", f"{t}.Research({PLAYER}.Self)", probe, lambda s: s != "未研究")

    # ------------------------------------------------------------ 法律
    def enact_law(self, law: str, snap: Snapshot) -> ActionResult:
        gd = gamedata.get()
        info = gd.laws.get(law)
        if not info:
            return ActionResult(False, f"推行 {law}", "没有这条法律")
        group = info["group"]
        current = snap.laws.get(group)
        if current is None:
            return ActionResult(False, f"推行 {law}", f"本国没有法律组 {group}")
        if current.key == law:
            return ActionResult(True, f"推行 {law}", "已是现行法律", law, law)
        names = {n for n in (info.get("name") or {}).values()}
        alts = self.b.rows(LAW_ALTERNATIVES, ["Law.GetLawType.GetName"], path=current.path)
        idx = next((i for i, (n,) in enumerate(alts) if plain(n) in names), None)
        if idx is None:
            return ActionResult(False, f"推行 {law}", f"{group} 的可选法律里没有它")
        path = current.path + [(LAW_ALTERNATIVES, idx)]

        def probe():
            try:
                n = plain(self.b.read(f"[{PLAYER}.GetLawBeingEnacted.GetLawType.GetName]"))
            except GameError:
                return None
            return law if n in names else n or None

        return self._run(f"推行 {law}", "Law.StartEnacting", probe, lambda s: s == law, path=path)

    # ------------------------------------------------------------ 建造
    def build(self, state_id: int, building: str, snap: Snapshot) -> ActionResult:
        s = snap.state(state_id)
        name = f"建造 {building} @ {s.name if s else state_id}"
        if not s or building not in s.buildings:
            return ActionResult(False, name, "这个州没有这种建筑的建造入口")
        row = s.buildings[building]
        key = self.b.read("[Building.GetBuildingType.GetKey]", row.path)
        if key != building:   # 列表在快照之后变了
            return ActionResult(False, name, f"路径已失效（现在指向 {key}），需要重新读局面")
        probe = lambda: int(float(self.b.read("[Building.GetExpansionLevelsInQueue]", row.path) or 0))
        before = probe()
        return self._run(name, "Building.QueueConstruction", probe, lambda q: q > before, path=row.path)

    # ------------------------------------------------------------ 生产方式
    def set_pm(self, state_id: int, building: str, pm: str, snap: Snapshot) -> ActionResult:
        s = snap.state(state_id)
        name = f"生产方式 {building} → {pm} @ {s.name if s else state_id}"
        row = s.buildings.get(building) if s else None
        if not row or row.levels <= 0:
            return ActionResult(False, name, "这个州没有建成的该建筑")
        groups = self.b.rows(PM_GROUPS, ["ProductionMethodGroup.GetKey",
                                         "Building.AccessProductionMethod(ProductionMethodGroup.Self).GetKey"],
                             path=row.path)
        for g, (gkey, cur) in enumerate(groups):
            gpath = row.path + [(PM_GROUPS, g)]
            options = [r[0] for r in self.b.rows(PM_OPTIONS, ["ProductionMethod.GetKey"], path=gpath)]
            if pm not in options:
                continue
            ppath = gpath + [(PM_OPTIONS, options.index(pm))]
            probe = lambda: self.b.read("[Building.AccessProductionMethod(ProductionMethodGroup.Self).GetKey]", gpath)
            return self._run(name, "ProductionMethod.GetSwitch(Building.Self)", probe, lambda v: v == pm, path=ppath)
        return ActionResult(False, name, "该建筑没有这个生产方式")


def states_index(b: Bridge) -> dict[int, int]:
    """州 id → AccessStates 下标（动作只需要路径时用，不必读完整快照）。"""
    rows = b.rows(STATES, ["State.GetID"])
    return {int(r[0]): i for i, r in enumerate(rows)}
