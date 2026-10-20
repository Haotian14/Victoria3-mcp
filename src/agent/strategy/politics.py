"""法律与政府：按游戏预计的通过率选法律；目标缺支持者时拉一个支持它的在野集团进政府。

立法规则（wiki Laws，1.13）：每个检查点（约 100 天）结果是推进 / 有利事件 / 受阻 / 辩论之一，
三次推进生效，三次受阻失败；失败或取消后两年不能再提。基础成功率 = 政府里支持这条法律的集团影响力之和
（+ 支持的运动 + 君主），受阻来自反对它的非边缘集团。所以：
- 只推通过率够高的（pass_chance ≥ min_pass），盲试只会把法律锁两年；
- 推不动的根源常常是政府组成。大清开局政府只有士大夫，几乎所有法律成功率为 0（docs/strategy.md「大清专题」），
  这时先改组政府：把影响力最大的、支持路线上首个只差支持者的目标的在野集团加进来。
  只加不减（defines：移出政府会让该集团 25% 支持者激进化），合法性留余量。

路线顺序在 data/strategy.json 的 law_route；概率与各集团态度都是游戏算的（observe.law_options），这里只做选择。
"""

from __future__ import annotations

from math import comb

from agent.observe import LawOption, Snapshot
from agent.strategy.config import Decision, cfg

PHASES = 3          # 推进几次生效
SETBACKS = 3        # 受阻几次失败


def pass_chance(opt: LawOption) -> float:
    """先攒满 PHASES 次推进、而不是先攒满 SETBACKS 次受阻的概率。辩论当作没有进展（只拖时间）；
    有利事件按推进算（它通常提高之后的成功率）。"""
    up = opt.success + opt.advance
    down = opt.stall
    if up <= 0:
        return 0.0
    if down <= 0:
        return 1.0
    p = up / (up + down)
    q = 1 - p
    return sum(comb(PHASES - 1 + k, k) * p ** PHASES * q ** k for k in range(SETBACKS))


def targets() -> list[tuple[str, str]]:
    return [(g, law) for g, law in cfg()["law_route"]]


def candidates(snap: Snapshot, options: list[LawOption], enacting: str | None) -> list[Decision]:
    """可推、且通过率达标的路线法律，按路线顺序。"""
    if enacting:
        return []
    need = cfg()["politics"]["min_pass"]
    out: list[Decision] = []
    for opt in options:
        current = snap.laws.get(opt.group)
        if current is None or current.key == opt.key or not opt.valid:
            continue
        chance = pass_chance(opt)
        if chance < need:
            continue
        out.append(Decision("enact_law", {"law": opt.key},
                            f"{opt.group}：{current.name} → {opt.name}，预计通过率 {chance:.0%}", chance))
    return out


def reform(snap: Snapshot, options: list[LawOption], enacting: str | None) -> Decision | None:
    """路线上排在最前、只差支持者的目标：拉一个支持它的在野集团进政府。已有可推的法律时不动政府。"""
    p = cfg()["politics"]
    if enacting or not snap.igs or candidates(snap, options, None):
        return None
    gov = [ig for ig in snap.igs if ig.in_gov]
    legit = snap.country.get("legitimacy") or 0.0
    if len(gov) >= p["max_government"] or legit < p["min_legitimacy_to_add"]:
        return None
    for opt in options:
        if not (opt.support_only or (opt.valid and pass_chance(opt) < p["min_pass"])):
            continue
        backers = [ig for ig in snap.igs if not ig.in_gov and not ig.marginal
                   and ig.clout >= p["min_clout_to_add"] and opt.stance.get(ig.name, 0) > 0]
        if not backers:
            continue
        best = max(backers, key=lambda ig: ig.clout)
        members = sorted(ig.index for ig in gov) + [best.index]
        return Decision("reform_government", {"members": members, "add": best.name},
                        f"{opt.name} 缺支持（推进 {opt.success + opt.advance:.0%} / 受阻 {opt.stall:.0%}），"
                        f"拉{best.name}（影响力 {best.clout:.0%}）进政府", best.clout)
    return None
