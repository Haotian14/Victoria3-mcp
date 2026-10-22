"""生产方式：已建成的建筑按「增加值 − 工资」挑每组最赚钱的已解锁方式。

- 只在差距明显时换：目标方式利润领先 SWITCH_MARGIN 以内的都算「可接受」，现行方式在其中就不动；
  换过的建筑 runner 冷却 24 个月。普鲁士自测里 10% 的门槛不够：纺织厂在两种方式间来回切了 34 次 ——
  自己一产出，那种商品就跌价，「最优」又翻回去，每次切换还有一段适应期的减产；
- 产出不是商品的方式组不碰（建造部门、行政机构）：模型只看得到投入成本、看不到建造点数，
  会把铁框架降回木制（普鲁士自测建造力因此从 45 掉到 24）；
- 投入在本国市场上没人卖（卖单为 0）的方式不选，否则一换就短缺；
- 每月最多处理 MAX_PER_MONTH 个建筑（按等级从大到小轮流），读列表很费往返。
"""

from __future__ import annotations

from agent.gamedata import GameData
from agent.observe import Snapshot
from agent.strategy import economy
from agent.strategy.config import Decision, cfg, profile
from agent.strategy.construction import _prices, _wage_rates

UNIVERSITY = "building_university"

SWITCH_MARGIN = 0.25
MAX_PER_MONTH = 12


def candidates(gd: GameData, snap: Snapshot, researched: set[str], offset: int = 0) -> list[Decision]:
    prices = _prices(gd, snap)
    laws = {l.key for l in snap.laws.values() if l.key}
    wages, wage_all = _wage_rates(snap)
    mix = cfg()["construction"]["wage_mix"]
    no_supply = {g for g, p in snap.prices.items() if not p.get("sell")}
    skip = set(cfg()["skip_buildings"])

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
            if len(options) < 2 or any(not gd.pms[pm]["outputs"] for pm in options):
                continue
            ranked = sorted(options, key=lambda pm: economy.pm_profit(gd, pm, prices, wage), reverse=True)
            best = economy.pm_profit(gd, ranked[0], prices, wage)
            ok = [pm for pm in ranked if economy.pm_profit(gd, pm, prices, wage) >= best - abs(best) * SWITCH_MARGIN]
            out.append(Decision("set_pm", {"state": s.id, "building": key, "pm": ranked[0], "acceptable": ok},
                                f"{s.name} {pmg}：每级周利润 {best:,.0f}"))
    return out


def university_candidates(gd: GameData, snap: Snapshot, researched: set[str]) -> list[Decision]:
    """大学：产出是创新、不是商品，经济账挑不了生产方式。按档案里的 pm_order 从低到高，
    取已解锁的最高一档（经院教育 → 哲学系 → 分析哲学系，创新 +50% / +100%）。"""
    order = (profile(snap).get("universities") or {}).get("pm_order") or []
    if not order:
        return []
    laws = {l.key for l in snap.laws.values() if l.key}
    out: list[Decision] = []
    for s in snap.states:
        row = s.buildings.get(UNIVERSITY)
        if row is None or row.levels <= 0:
            continue
        unlocked = [pm for pm in order if pm in gd.pms and economy.pm_unlocked(gd, pm, researched, laws)]
        if not unlocked:
            continue
        best = unlocked[-1]
        out.append(Decision("set_pm", {"state": s.id, "building": UNIVERSITY, "pm": best, "acceptable": [best]},
                            f"{s.name} 大学 → {gd.pms[best]['name'].get('zh', best)}（创新更高）"))
    return out[:8]
