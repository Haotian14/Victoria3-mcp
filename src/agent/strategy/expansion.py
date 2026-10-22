"""并入未合并州：当前最确定的低风险扩张（殖民/战争留到后期）。

1.13 调研：未合并州吃 −25% 基础设施、−10% 吞吐、−50% 重工业建造效率等一整套惩罚；
大清有 9 个未合并州（Hinggan、Qinghai 等），并入后税收/建造/生活水平都会改善。
代价是官僚与整合时间，所以税收浪费太高时先不并入；同时最多 2 个，按人口排序。
"""

from __future__ import annotations

from agent.observe import Snapshot
from agent.strategy.config import Decision, profile


def candidates(snap: Snapshot) -> list[Decision]:
    spec = profile(snap).get("incorporate") or {}
    if not spec:
        return []
    waste = snap.country.get("tax_waste") or 0.0
    if waste >= float(spec.get("max_tax_waste", 0.10)):
        return []
    pool = [s for s in snap.states
            if not s.incorporated and not s.incorporating and s.can_incorporate]
    pool.sort(key=lambda s: s.population or 0, reverse=True)
    return [Decision("state_action", {"state": s.id, "cmd": "IncorporateState"},
                     f"并入未合并州 {s.name}（人口 {s.population or 0:,.0f}；"
                     f"当前税收浪费 {waste:.0%}）")
            for s in pool[: int(spec.get("max_per_month", 2))]]
