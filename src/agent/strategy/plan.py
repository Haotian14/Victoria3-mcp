"""每月一次的总决策：把各模块的候选合成一份计划。

各组的执行语义（runner 负责）：
- tax：至多一条；
- reform：至多一条，改组政府（之后本月不再推法律：成功率要等下个月按新政府重算）；
- research / law：按顺序尝试，第一条成功即止（游戏同时只能研究一项、推行一条法律）；
- build：按顺序尝试，成功 build_slots 个即止；
- pm：逐条尝试（现行方式已可接受时 Actions 直接跳过）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agent.gamedata import GameData
from agent.observe import LawOption, Snapshot
from agent.strategy import budget, construction, politics, production, research
from agent.strategy.config import Decision


@dataclass
class Plan:
    tax: Decision | None = None
    reform: Decision | None = None
    research: list[Decision] = field(default_factory=list)
    law: list[Decision] = field(default_factory=list)
    build: list[Decision] = field(default_factory=list)
    build_slots: int = 0
    pm: list[Decision] = field(default_factory=list)

    def summary(self, limit: int = 5) -> list[str]:
        lines = []
        if self.tax:
            lines.append(f"税：{self.tax}")
        if self.research:
            lines.append(f"研究：{self.research[0]}")
        if self.reform:
            lines.append(f"政府：{self.reform}")
        if self.law:
            lines.append(f"法律：{self.law[0]}")
        lines += [f"建造：{d}" for d in self.build[:max(self.build_slots, 0)][:limit]]
        lines += [f"生产方式：{d}" for d in self.pm[:limit]]
        return lines


def decide(gd: GameData, snap: Snapshot, researched: set[str], costs: dict[str, float],
           enacting: str | None, pm_offset: int = 0, law_options: list[LawOption] | None = None) -> Plan:
    options = law_options or []
    return Plan(
        tax=budget.decide(snap),
        reform=politics.reform(snap, options, enacting),
        research=research.candidates(gd, researched, snap.researching),
        law=politics.candidates(snap, options, enacting),
        build=construction.candidates(gd, snap, researched, costs),
        build_slots=construction.slots(snap),
        pm=production.candidates(gd, snap, researched, pm_offset),
    )
