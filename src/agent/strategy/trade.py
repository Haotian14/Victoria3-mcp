"""贸易政策：用关税 / 补贴修市场缺货。

攻略共识（1.13 贸易是自治路线，政府只调关税 / 补贴）：
- 缺货：进口关税降到 0（让进口路线长起来），出口关税拉高（优先国内供给，别被外国买走）；
- 过剩：进口高关税保护本国产业，出口补贴把多余产能卖出去。
关税按基准价计，木材/煤这类低价大宗的关税影响被放大；这里只对档案列出的关键商品动手。
"""

from __future__ import annotations

from agent.observe import Snapshot
from agent.strategy.config import Decision, profile

DEFAULT_GOODS = ("meat", "wood", "hardwood", "groceries", "iron", "tools", "luxury_clothes", "fabric", "coal")


def _ratio(p: dict) -> tuple[float, float]:
    buy = float(p.get("buy") or 0.0)
    sell = float(p.get("sell") or 0.0)
    return buy / max(sell, 1.0), sell / max(buy, 1.0)


def candidates(snap: Snapshot) -> list[Decision]:
    spec = profile(snap).get("trade") or {}
    if not spec:
        return []
    goods = spec.get("goods") or DEFAULT_GOODS
    short = float(spec.get("shortage_ratio", 1.2))
    over = float(spec.get("oversupply_ratio", 1.3))
    out: list[Decision] = []
    for g in goods:
        p = snap.prices.get(g) or {}
        if not p.get("buy") and not p.get("sell"):
            continue
        buy_ratio, sell_ratio = _ratio(p)
        if buy_ratio >= short:
            out.append(Decision("trade_policy", {"goods": g, "side": "Import", "policy": "TariffsNone"},
                                f"{g} 缺货（买单/卖单 {buy_ratio:.1f}）：进口零关税", score=2e4 + buy_ratio))
            out.append(Decision("trade_policy", {"goods": g, "side": "Export", "policy": "TariffsMax"},
                                f"{g} 缺货：出口高关税，优先国内供给", score=2e4 + buy_ratio - 0.1))
        elif sell_ratio >= over:
            out.append(Decision("trade_policy", {"goods": g, "side": "Import", "policy": "TariffsMax"},
                                f"{g} 过剩（卖单/买单 {sell_ratio:.1f}）：进口高关税", score=1e4 + sell_ratio))
            out.append(Decision("trade_policy", {"goods": g, "side": "Export", "policy": "SubventionsMax"},
                                f"{g} 过剩：出口补贴", score=1e4 + sell_ratio - 0.1))
    out.sort(key=lambda d: d.score, reverse=True)
    return out[: int(spec.get("max_per_month", 6))]
