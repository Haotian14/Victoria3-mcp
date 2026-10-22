"""机构投入：只在国家档案给出目标时推（大清：教育 2 级）。

依据（社区共识 + 游戏机制）：识字率只由教育机构等级和 pop 财富决定（每级 +10%），
识字率又决定创新上限与科技扩散；大清早期教育机构上限低，先把教育拉到 2 级，等公立学校再往上。
机构不存在（还没通过学校法）时动作层会报错，runner 锁 12 个月再试；税收浪费高说明官僚不够，
先别加机构负担，等行政机构补上来。
"""

from __future__ import annotations

from agent.observe import Snapshot
from agent.strategy.config import Decision, profile


def candidates(snap: Snapshot) -> list[Decision]:
    spec = profile(snap).get("institutions") or {}
    waste = snap.country.get("tax_waste") or 0.0
    out: list[Decision] = []
    if waste > 0.2:                              # 官僚不够：先补行政机构，别再加机构
        return out
    for name, level in spec.items():
        if name.startswith("_"):
            continue
        out.append(Decision("set_institution", {"institution": name, "level": int(level)},
                            f"机构「{name}」投入 → {level}（税收浪费 {waste:.0%}）"))
    return out
