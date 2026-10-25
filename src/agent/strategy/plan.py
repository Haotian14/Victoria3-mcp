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
from agent.strategy import budget, companies, construction, consumption, decrees, expansion, institutions, politics, production, privatization, research, subsidies, trade
from agent.strategy import config as strategy_config
from agent.strategy.config import Decision


@dataclass
class Plan:
    tax: Decision | None = None
    reform: Decision | None = None
    research: list[Decision] = field(default_factory=list)
    research_queue: list[Decision] = field(default_factory=list)
    law: list[Decision] = field(default_factory=list)
    institution: list[Decision] = field(default_factory=list)
    decree: list[Decision] = field(default_factory=list)
    incorporate: list[Decision] = field(default_factory=list)
    privatize: list[Decision] = field(default_factory=list)
    company: list[Decision] = field(default_factory=list)
    subsidy: list[Decision] = field(default_factory=list)
    consumption: list[Decision] = field(default_factory=list)
    trade: list[Decision] = field(default_factory=list)
    build: list[Decision] = field(default_factory=list)
    build_slots: int = 0
    pm: list[Decision] = field(default_factory=list)

    def summary(self, limit: int = 5) -> list[str]:
        lines = []
        if self.tax:
            lines.append(f"税：{self.tax}")
        if self.research:
            lines.append(f"研究：{self.research[0]}")
        lines += [f"研究队列：{d.args['tech']}" for d in self.research_queue[:limit]]
        if self.reform:
            lines.append(f"政府：{self.reform}")
        if self.law:
            lines.append(f"法律：{self.law[0]}")
        lines += [f"机构：{d}" for d in self.institution[:limit]]
        lines += [f"法令：{d}" for d in self.decree[:limit]]
        lines += [f"并入：{d}" for d in self.incorporate[:limit]]
        lines += [f"私有化：{d}" for d in self.privatize[:limit]]
        lines += [f"公司：{d}" for d in self.company[:limit]]
        lines += [f"补贴：{d}" for d in self.subsidy[:limit]]
        lines += [f"消费税：{d}" for d in self.consumption[:limit]]
        lines += [f"贸易：{d}" for d in self.trade[:limit]]
        lines += [f"建造：{d}" for d in self.build[:max(self.build_slots, 0)][:limit]]
        lines += [f"生产方式：{d}" for d in self.pm[:limit]]
        return lines


def decide(gd: GameData, snap: Snapshot, researched: set[str], costs: dict[str, float],
           enacting: str | None, pm_offset: int = 0, law_options: list[LawOption] | None = None,
           law_stall: int = 0) -> Plan:
    options = law_options or []
    commitment = politics.commitment_target(snap, options) if not enacting else None
    fallback = politics.fallback_ready(snap, law_stall)
    if commitment is not None and not fallback:
        options = [commitment]  # 先补路线首法支持，不让后面的100%警察法占住立法槽
    next_law = None
    for group, key in politics.targets(snap):
        current = snap.laws.get(group)
        if current and current.key != key:
            next_law = key
            opt = next((o for o in (law_options or []) if o.key == key), None)
            if opt and politics.institution_block(snap, opt) and snap.country.get('institution_level_cost') is not None:
                snap.country['bureaucracy_target'] = abs(snap.country['institution_level_cost']) + float(
                    strategy_config.profile(snap).get('institution_bureaucracy_buffer', 500))
            break
    economy = snap.laws.get('lawgroup_economic_system')
    c = snap.country
    if (economy and economy.key == 'law_traditionalism'
            and (enacting == 'law_interventionism' or next_law == 'law_interventionism')
            and c.get('bureaucracy_income') is not None and c.get('bureaucracy') is not None):
        # 传统主义的人口行政花费-25%将消失：按非机构消耗估算预留，实际差额继续驱动补建。
        population_cost = max(0, c['bureaucracy_income'] - c['bureaucracy'] - (c.get('institutions') or 0))
        c['bureaucracy_target'] = max(float(c.get('bureaucracy_target') or 500), population_cost / 3 + 500)
    build = construction.candidates(gd, snap, researched, costs)
    # 队列硬停时 slots()=0，但优先项目（部门/食品/行政/大学/贸易中心）仍值得排 2 个
    build_slots = construction.slots(snap)
    return Plan(
        tax=budget.decide(snap),
        reform=politics.reform(snap, options, enacting, fallback),
        research=research.candidates(gd, researched, snap.researching, strategy_config.tech_priority(snap),
                                     strategy_config.tech_blacklist(snap)),
        law=politics.candidates(snap, options, enacting, fallback),
        institution=institutions.candidates(snap),
        decree=decrees.candidates(snap),
        incorporate=expansion.candidates(snap),
        privatize=privatization.candidates(snap),
        company=companies.candidates(snap),
        subsidy=subsidies.candidates(snap),
        consumption=consumption.candidates(snap),
        trade=trade.candidates(snap),
        build=build,
        build_slots=build_slots,
        pm=production.candidates(gd, snap, researched, pm_offset)
           + production.logging_candidates(gd, snap, researched)
           + production.university_candidates(gd, snap, researched)
           + production.financial_candidates(gd, snap, researched)
           + production.construction_pm_candidates(gd, snap, researched),
    )
