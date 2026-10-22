"""贸易政策：用关税 / 补贴修市场缺货。

攻略共识（1.13 贸易是自治路线，政府只调关税 / 补贴）：
- 缺货：进口关税降到 0（让进口路线长起来），出口关税拉高（优先国内供给，别被外国买走）；
- 过剩：进口高关税保护本国产业，出口补贴把多余产能卖出去。

1.13 调研补充：
- 七档互斥（同一商品同一方向只有一个政策），所以先读当前档位，只发“与目标不同”的动作；
- 切换有 3 个月 + 7 天冷却，runner 对每次尝试锁 4 个月，避免每月翻转；
- 同时看买单/卖单与价格/基准价；退出阈值低于进入阈值，留迟滞；
- 一次最多 2 条，先缺货后过剩；不常驻 Max（广州体系 Max 也只有 50%）。
"""

from __future__ import annotations

from agent.observe import Snapshot
from agent.strategy.config import Decision, profile

DEFAULT_GOODS = ("meat", "wood", "groceries", "iron", "tools", "coal")


def _signal(p: dict) -> tuple[float, float, float]:
    buy = float(p.get("buy") or 0.0)
    sell = float(p.get("sell") or 0.0)
    price = float(p.get("price") or 0.0)
    base = float(p.get("base") or 0.0)
    return buy / max(sell, 1.0), sell / max(buy, 1.0), (price / base if base else 0.0)


def candidates(snap: Snapshot) -> list[Decision]:
    spec = profile(snap).get("trade") or {}
    if not spec or snap.trade_policies is None:
        return []
    goods = spec.get("goods") or DEFAULT_GOODS
    short = float(spec.get("shortage_ratio", 1.2))
    severe = float(spec.get("severe_ratio", 1.5))
    price_short = float(spec.get("price_shortage_ratio", 1.25))
    price_exit = float(spec.get("price_exit_ratio", 1.1))
    exit_ratio = float(spec.get("exit_ratio", 1.05))
    over = float(spec.get("oversupply_ratio", 1.3))
    out: list[Decision] = []
    for g in goods:
        cur = snap.trade_policies.get(g) or {}
        if not cur:
            continue
        p = snap.prices.get(g) or {}
        if not p.get("buy") and not p.get("sell"):
            continue
        buy_ratio, sell_ratio, price_ratio = _signal(p)
        cur_i, cur_e = cur.get("Import", ""), cur.get("Export", "")
        if buy_ratio >= short or price_ratio >= price_short:
            if cur_i != "TariffsNone":
                out.append(Decision("trade_policy", {"goods": g, "side": "Import", "policy": "TariffsNone"},
                                    f"{g} 缺货（买单/卖单 {buy_ratio:.1f}，价格/基准 {price_ratio:.2f}）："
                                    f"进口零关税", score=2e4 + buy_ratio))
            if (buy_ratio >= severe or price_ratio >= severe) and cur_e not in ("TariffsHigh", "TariffsMax"):
                out.append(Decision("trade_policy", {"goods": g, "side": "Export", "policy": "TariffsHigh"},
                                    f"{g} 严重缺货：出口高关税，优先国内供给",
                                    score=2e4 + buy_ratio - 0.1))
        elif sell_ratio >= over:
            if cur_i not in ("TariffsHigh", "TariffsMax"):
                out.append(Decision("trade_policy", {"goods": g, "side": "Import", "policy": "TariffsHigh"},
                                    f"{g} 过剩（卖单/买单 {sell_ratio:.1f}）：进口高关税保护本国产业",
                                    score=1e4 + sell_ratio))
        elif buy_ratio <= exit_ratio and price_ratio <= price_exit:
            if cur_i not in ("TariffsLow", ""):
                out.append(Decision("trade_policy", {"goods": g, "side": "Import", "policy": "TariffsLow"},
                                    f"{g} 贸易恢复正常（买单/卖单 {buy_ratio:.2f}）：进口关税回 Low",
                                    score=1e3 + buy_ratio))
            if cur_e in ("TariffsHigh", "TariffsMax", "SubventionsLow", "SubventionsHigh", "SubventionsMax"):
                out.append(Decision("trade_policy", {"goods": g, "side": "Export", "policy": "TariffsLow"},
                                    f"{g} 缺货缓解：出口关税回 Low", score=1e3 + buy_ratio - 0.1))
    out.sort(key=lambda d: d.score, reverse=True)
    return out[: int(spec.get("max_per_month", 2))]
