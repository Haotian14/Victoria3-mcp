"""法律：按 data/strategy.json 的 law_route 依次推行，同一时间只推一条（游戏规则）。

路线偏经济：传统主义 → 干预主义（投资池建造）、按人头征税、佃农制、保护主义、宗教学校……
能否推行（利益集团支持、前置科技 / 法律）以游戏的 IsValid(Law.StartEnacting) 为准，这里只排顺序。
"""

from __future__ import annotations

from agent.observe import Snapshot
from agent.strategy.config import Decision, cfg


def candidates(snap: Snapshot, enacting: str | None) -> list[Decision]:
    if enacting:
        return []
    out: list[Decision] = []
    for group, law in cfg()["law_route"]:
        current = snap.laws.get(group)
        if current is None or current.key == law:
            continue
        out.append(Decision("enact_law", {"law": law}, f"{group}：{current.name} → {law}"))
    return out
