"""研究：按 data/strategy.json 的 tech_priority 依次推进，缺前置时先研究前置。

返回按优先级排好的候选（多个），由 runner 依次尝试，第一个游戏判定可研究的生效 ——
可研究与否（是否已在研究、前置是否满足、是否已完成）以游戏的 IsValid 为准，这里只排顺序。
"""

from __future__ import annotations

from agent.gamedata import GameData
from agent.strategy.config import Decision, cfg


def _path(gd: GameData, target: str, done: set[str]) -> list[str]:
    """目标科技还缺的前置，按先后（前置在前）。"""
    order: list[str] = []
    seen: set[str] = set()

    def visit(t: str) -> None:
        if t in seen or t in done or t not in gd.techs:
            return
        seen.add(t)
        for r in gd.techs[t].get("requires", []):
            visit(r)
        order.append(t)

    visit(target)
    return order


def candidates(gd: GameData, researched: set[str], researching: str | None,
               priority: list[str] | None = None) -> list[Decision]:
    if researching:
        return []
    out: list[Decision] = []
    seen: set[str] = set()
    for target in (priority or cfg()["tech_priority"]):
        for t in _path(gd, target, researched):
            if t not in seen:
                seen.add(t)
                why = "优先科技" if t == target else f"{target} 的前置"
                out.append(Decision("research", {"tech": t}, why))
    # 优先表走完后：时代最早的生产科技优先，研究槽别空着
    rest = sorted((k for k, v in gd.techs.items() if k not in researched and k not in seen and v.get("can_research", True)),
                  key=lambda k: (gd.techs[k]["era"], gd.techs[k]["category"] != "production", k))
    out += [Decision("research", {"tech": t}, "优先表外，按时代补位") for t in rest[:20]]
    return out
