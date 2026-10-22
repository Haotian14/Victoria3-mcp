"""州法令（消耗权威力）：按国家档案在关键州颁布。

大清 1836 攻略：识字率低时用权威力开「促进社会流动」（教育机会 +25%、资质 +25%），
基础设施吃紧的州开「道路养护」（基础设施 + 建造速度 +10%）。法令名是游戏里的中文名。
同一州重复提同一法令时，动作层会返回「已是目标状态」，不会重复花钱。
"""

from __future__ import annotations

from agent.observe import Snapshot, StateRow
from agent.strategy.config import Decision, profile


def _pick_states(snap: Snapshot, opt: dict) -> list[StateRow]:
    if opt.get("only_infra_overuse"):
        rows = [s for s in snap.states
                if s.incorporated and not s.isolated
                and s.infrastructure is not None and s.infrastructure_usage is not None
                and s.infrastructure_usage > s.infrastructure]
        return sorted(rows, key=lambda s: (s.infrastructure_usage or 0) - (s.infrastructure or 0), reverse=True)
    min_pop = float(opt.get("min_population") or 0)
    rows = [s for s in snap.states
            if s.incorporated and not s.isolated and (s.population or 0) >= min_pop]
    return sorted(rows, key=lambda s: s.population or 0, reverse=True)


def candidates(snap: Snapshot) -> list[Decision]:
    spec = profile(snap).get("decrees") or {}
    out: list[Decision] = []
    for name, opt in spec.items():
        if name.startswith("_"):
            continue
        n = int(opt.get("max_states", 1))
        for s in _pick_states(snap, opt)[:n]:
            out.append(Decision("set_decree", {"state": s.id, "decree": name},
                                f"{s.name} 颁布「{name}」（人口 {s.population or 0:,.0f}）"))
    return out
