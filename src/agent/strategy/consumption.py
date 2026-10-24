"""消费税：先向奢侈品要收入，但目标是人均 GDP/SoL，能退则退。

财政调研（1.13.11，见 docs/research-progress.md）：
- 每项持续消耗权威力，默认 100（谷物 500、布料/木材/杂货 300、肉/纸 200），
  所以只征茶、酒、鸦片、烟草、糖、瓷器这类奢侈品；
- 不直接扣合法性，但会推高售价、压低 SoL，并且同样吃税收浪费；
- 一次只开 / 退一项，观察 4 周；权威力不足时不开，避免和法令抢容量。

目标改为人均 GDP + SoL 后：最多保留 max_goods 项；SoL 低于 repeal_below_sol 时只保留
keep_when_low_sol 项（默认只留茶）。退出要先看预算：结余为正，或国库 >26 周开支且赤字
≤3% 收入才退，避免为了 SoL 把国库拖进借债。
"""

from __future__ import annotations

from agent.observe import Snapshot
from agent.strategy.config import Decision, cfg, profile

DEFAULT_ORDER = ("tea", "liquor", "opium", "tobacco", "sugar", "porcelain")


def _affordable(snap: Snapshot, spec: dict) -> bool:
    """退消费税的预算护栏：结余为正，或国库够厚且赤字很小。"""
    balance = snap.country.get("balance") or 0.0
    if balance >= 0:
        return True
    money = snap.country.get("money") or 0.0
    expenses = snap.country.get("expenses") or 0.0
    income = snap.country.get("income") or 1.0
    weeks = float(spec.get("repeal_reserve_weeks", 26))
    ratio = float(spec.get("repeal_max_deficit_ratio", 0.03))
    return bool(expenses and money > expenses * weeks and balance > -income * ratio)


def candidates(snap: Snapshot) -> list[Decision]:
    spec = profile(snap).get("consumption_tax") or cfg().get("consumption_tax") or {}
    if not spec or snap.taxed_goods is None:
        return []
    order = list(spec.get("goods") or DEFAULT_ORDER)
    taxed = [g for g in order if g in set(snap.taxed_goods)]
    active = len(taxed)
    sol = snap.country.get("sol") or 0.0
    target = int(spec.get("max_goods", 6))
    low_sol = sol > 0 and sol < float(spec.get("repeal_below_sol", 0.0))
    if low_sol:
        target = min(target, int(spec.get("keep_when_low_sol", 1)))

    # 先退：优先退最后加的、对民生影响最大的奢侈品（瓷器/糖/烟草/鸦片/酒/茶）
    if active > target:
        if not _affordable(snap, spec):
            return []
        for goods in reversed(taxed):
            return [Decision("toggle_consumption_tax", {"goods": goods, "on": False},
                             f"退出消费税 {goods}（SoL {sol:.2f}，已开 {active} 项，目标 ≤{target}；"
                             f"预算允许）")]
        return []

    # SoL 已经偏低：不再新开，哪怕还没到上限
    if low_sol or active >= target:
        return []
    leg = snap.country.get("legitimacy") or 0.0
    waste = snap.country.get("tax_waste") or 0.0
    authority = snap.country.get("authority")
    if leg < float(spec.get("min_legitimacy", 45)) or sol < float(spec.get("min_sol", 6.0)):
        return []
    if waste > float(spec.get("max_tax_waste", 0.12)) or authority is None:
        return []
    cost = float(spec.get("cost_per_good", 100))
    buffer = float(spec.get("min_authority_buffer", 100))
    if authority < cost + buffer:
        return []
    for goods in order:
        if goods in taxed:
            continue
        return [Decision("toggle_consumption_tax", {"goods": goods, "on": True},
                         f"开征消费税 {goods}（权威 {authority:.0f}，每项约 {cost:.0f}，"
                         f"已开 {active}/{target} 项）")]
    return []
