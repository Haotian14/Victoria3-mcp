"""生产方式：已建成的建筑按「增加值 − 工资」挑每组最赚钱的已解锁方式。

- 只在差距明显时换：目标方式利润领先 SWITCH_MARGIN 以内的都算「可接受」，现行方式在其中就不动，
  避免价格小幅波动时来回切（切换期间建筑会有一段适应期）；
- 投入在本国市场上没人卖（卖单为 0）的方式不选，否则一换就短缺；
- 每月最多处理 MAX_PER_MONTH 个建筑（按等级从大到小轮流），读列表很费往返。
"""

from __future__ import annotations

from agent.gamedata import GameData
from agent.observe import Snapshot
from agent.strategy import economy
from agent.strategy.config import Decision, cfg
from agent.strategy.construction import _prices, _wage_rates

SWITCH_MARGIN = 0.10
MAX_PER_MONTH = 12


def candidates(gd: GameData, snap: Snapshot, researched: set[str], offset: int = 0) -> list[Decision]:
    prices = _prices(gd, snap)
    laws = {l.key for l in snap.laws.values() if l.key}
    wages, wage_all = _wage_rates(snap)
    mix = cfg()["construction"]["wage_mix"]
    no_supply = {g for g, p in snap.prices.items() if not p.get("sell")}
    skip = set(cfg()["skip_buildings"]) - {"building_construction_sector"}

    owned = [(s, key, row) for s in snap.states for key, row in s.buildings.items()
             if row.levels > 0 and key in gd.buildings and key not in skip and "subsistence" not in key]
    owned.sort(key=lambda t: -t[2].levels)
    if not owned:
        return []
    start = offset % len(owned)
    owned = owned[start:] + owned[:start]

    out: list[Decision] = []
    for s, key, row in owned[:MAX_PER_MONTH]:
        wage = wages.get(s.id, wage_all) * mix / 1000.0
        for pmg in gd.buildings[key]["pmgs"]:
            options = [pm for pm in (gd.pmgs.get(pmg) or {}).get("pms", [])
                       if economy.pm_unlocked(gd, pm, researched, laws)
                       and not (set(gd.pms[pm]["inputs"]) & no_supply)]
            if len(options) < 2:
                continue
            ranked = sorted(options, key=lambda pm: economy.pm_profit(gd, pm, prices, wage), reverse=True)
            best = economy.pm_profit(gd, ranked[0], prices, wage)
            ok = [pm for pm in ranked if economy.pm_profit(gd, pm, prices, wage) >= best - abs(best) * SWITCH_MARGIN]
            out.append(Decision("set_pm", {"state": s.id, "building": key, "pm": ranked[0], "acceptable": ok},
                                f"{s.name} {pmg}：每级周利润 {best:,.0f}"))
    return out
