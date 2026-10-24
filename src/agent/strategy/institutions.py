"""机构投入：只在国家档案给出目标时推（大清：教育 2 级）。

依据（社区共识 + 游戏机制）：识字率只由教育机构等级和 pop 财富决定（每级 +10%），
识字率又决定创新上限与科技扩散；大清早期教育机构上限低，先把教育拉到 2 级，等公立学校再往上。
机构不存在（还没通过学校法/卫生法）时快照的机构列表里就没有它，这里直接跳过，不再每月发一次
注定失败的动作。1.13.11 机构基础上限是 1，靠科技/法律才提高到 2+，所以档案里的目标从 1 起步；
税收浪费 >5% 或结余为负时先别加机构负担（每级约 3,500–3,900 官僚），等行政机构补上来。
"""

from __future__ import annotations

from agent.observe import Snapshot
from agent.strategy.config import Decision, profile


def candidates(snap: Snapshot) -> list[Decision]:
    prof = profile(snap)
    spec = dict(prof.get("institutions") or {})
    # 攻略：1860 后国库充足时学校/医院升到 5 级（识字率/卫生接近满值）。
    late_year = int(prof.get("institutions_late_year", 0) or 0)
    if late_year and snap.date.year >= late_year:
        limit = snap.country.get("gold_limit") or 0.0
        money = snap.country.get("money") or 0.0
        if limit and money > limit * float(prof.get("institutions_late_reserve_ratio", 1.5)):
            spec.update(prof.get("institutions_late") or {})
    gate = prof.get("institution_gate") or {}
    waste = snap.country.get("tax_waste") or 0.0
    balance = snap.country.get("balance") or 0.0
    out: list[Decision] = []
    max_waste = float(gate.get("max_tax_waste", 0.05))
    if waste > max_waste:
        return out                               # 每级机构约 3,500–3,900 官僚：先补行政机构
    if gate.get("require_positive_balance", True) and balance <= 0:
        return out                               # 结余为负先别加机构负担
    for name, level in spec.items():
        if name.startswith("_"):
            continue
        if snap.institutions is not None and name not in snap.institutions:
            continue                             # 还没解锁（如学校法未过时的教育机构）
        out.append(Decision("set_institution", {"institution": name, "level": int(level)},
                            f"机构「{name}」投入 → {level}（税收浪费 {waste:.0%}）"))
    return out
