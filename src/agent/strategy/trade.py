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
    price_over = float(spec.get("price_oversupply_ratio", 0.8))
    exit_ratio = float(spec.get("exit_ratio", 1.05))
    over = float(spec.get("oversupply_ratio", 1.3))
    balance = snap.country.get("balance") or 0.0
    journals = snap.journal_keys or set()
    proactive = set(spec.get("proactive_imports") or ())
    proactive_until = int(spec.get("proactive_until_year", 0) or 0)
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
        # 攻略：前期主动对木材/硬木/铁开进口零关税，不等缺货，提前锁定廉价投入。
        proactive_import = bool(g in proactive and proactive_until and snap.date.year < proactive_until)
        if proactive_import:
            if cur_i != "TariffsNone":
                out.append(Decision("trade_policy", {"goods": g, "side": "Import", "policy": "TariffsNone"},
                                    f"{g} 前期主动进口：零关税锁定廉价投入（攻略）",
                                    score=2.5e4 + buy_ratio))
                cur_i = "TariffsNone"
            # 缺货时继续走下面的出口高关税；正常时保持零关税，不回到 Low
            if not (buy_ratio >= short or price_ratio >= price_short):
                continue
        # 攻略：晚期国内资源耗尽，对铁/木材付进口补贴，保证工厂原料。
        late = set(spec.get("late_import_subventions") or ())
        late_year = int(spec.get("late_import_subvention_year", 0) or 0)
        if (g in late and late_year and snap.date.year >= late_year and balance > 0
                and price_ratio >= float(spec.get("late_import_subvention_ratio", 1.5))):
            target_policy = spec.get("late_import_subvention_policy", "SubventionsLow")
            if cur_i not in ("SubventionsLow", "SubventionsHigh", "SubventionsMax"):
                out.append(Decision("trade_policy", {"goods": g, "side": "Import", "policy": target_policy},
                                    f"{g} 晚期原材料短缺（价格/基准 {price_ratio:.2f}）：进口补贴",
                                    score=2.6e4 + price_ratio))
            continue
        # 「建立纸张进口」JE 的完成条件：首都 paper 进口补贴（low/high/max_subventions）+ 价格不超过基准 20%。
        # 这里必须用进口补贴，不是零关税；否则 JE 永远完不成。
        if g == "paper" and "je_set_up_paper_import" in journals:
            if cur_i not in ("SubventionsLow", "SubventionsHigh", "SubventionsMax"):
                out.append(Decision("trade_policy", {"goods": g, "side": "Import", "policy": "SubventionsLow"},
                                    f"paper 进口补贴（日志「建立纸张进口」要求；价格/基准 {price_ratio:.2f}）",
                                    score=5e4))
            continue
        if buy_ratio >= short or price_ratio >= price_short:
            if cur_i != "TariffsNone":
                out.append(Decision("trade_policy", {"goods": g, "side": "Import", "policy": "TariffsNone"},
                                    f"{g} 缺货（买单/卖单 {buy_ratio:.1f}，价格/基准 {price_ratio:.2f}）："
                                    f"进口零关税", score=2e4 + buy_ratio))
            if (buy_ratio >= severe or price_ratio >= severe) and cur_e not in ("TariffsHigh", "TariffsMax"):
                out.append(Decision("trade_policy", {"goods": g, "side": "Export", "policy": "TariffsHigh"},
                                    f"{g} 严重缺货：出口高关税，优先国内供给",
                                    score=2e4 + buy_ratio - 0.1))
        elif sell_ratio >= over or (price_ratio and price_ratio <= price_over):
            if cur_i not in ("TariffsHigh", "TariffsMax"):
                out.append(Decision("trade_policy", {"goods": g, "side": "Import", "policy": "TariffsHigh"},
                                    f"{g} 过剩（卖单/买单 {sell_ratio:.1f}，价格/基准 {price_ratio:.2f}）："
                                    f"进口高关税保护本国产业", score=1e4 + sell_ratio))
            # 出口侧也要处理：过剩时出口零关税；严重过剩且结余为正才用出口补贴
            severe_over = sell_ratio >= severe or (price_ratio and price_ratio <= max(0.0, price_over - 0.15))
            target_e = "SubventionsLow" if severe_over and balance > 0 else "TariffsNone"
            if target_e == "SubventionsLow":
                needs = cur_e not in ("SubventionsLow", "SubventionsHigh", "SubventionsMax")
            else:
                needs = cur_e in ("TariffsLow", "TariffsHigh", "TariffsMax")
            if needs:
                out.append(Decision("trade_policy", {"goods": g, "side": "Export", "policy": target_e},
                                    f"{g} 过剩：出口{ '低补贴' if target_e == 'SubventionsLow' else '零关税'}，鼓励外销",
                                    score=1e4 + sell_ratio - 0.2))
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
