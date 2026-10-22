"""消费税：先向奢侈品要收入，不碰民生品。

财政调研（1.13.11，见 docs/research-progress.md）：
- 每项持续消耗权威力，默认 100（谷物 500、布料/木材/杂货 300、肉/纸 200），
  所以只征茶、酒、鸦片、烟草、糖、瓷器这类奢侈品；
- 不直接扣合法性，但会推高售价、压低 SoL，并且同样吃税收浪费；
- 一次只开一项，开完观察 4 周；权威力不足时不开，避免和法令抢容量；
- 先开茶 → 酒 → 鸦片，稳定后再扩到 6 项。
"""

from __future__ import annotations

from agent.observe import Snapshot
from agent.strategy.config import Decision, cfg, profile

DEFAULT_ORDER = ("tea", "liquor", "opium", "tobacco", "sugar", "porcelain")


def candidates(snap: Snapshot) -> list[Decision]:
    spec = profile(snap).get("consumption_tax") or cfg().get("consumption_tax") or {}
    if not spec or snap.taxed_goods is None:
        return []
    order = list(spec.get("goods") or DEFAULT_ORDER)
    taxed = set(snap.taxed_goods)
    if len(taxed & set(order)) >= int(spec.get("max_goods", 6)):
        return []
    leg = snap.country.get("legitimacy") or 0.0
    sol = snap.country.get("sol") or 0.0
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
                         f"已开 {len(taxed & set(order))} 项）")]
    return []
