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
from agent.strategy import config as strategy_config
from agent.strategy.config import Decision, cfg, profile

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


def _pcfg(snap: Snapshot) -> dict:
    """通用 politics 参数 + 国家档案覆盖（大清：min_pass 0.35、max_government 3 等）。"""
    p = dict(cfg()["politics"])
    p.update(profile(snap).get("politics") or {})
    p["ruler_ig"] = profile(snap).get("ruler_ig", "")
    return p


def _gov_limit(snap: Snapshot, p: dict) -> int:
    """政府规模上限按权力分配法律走：独裁 1（+基础 1=2），寡头/技术治国 3。"""
    law = snap.laws.get("lawgroup_distribution_of_power")
    key = (law.key if law else "") or ""
    limits = p.get("government_limits") or {}
    return int(limits.get(key, p.get("max_government", 3)))


def fallback_threshold(snap: Snapshot) -> int:
    return int(_pcfg(snap).get("fallback_after_months", 24))


def fallback_min_pass(snap: Snapshot) -> float:
    return float(_pcfg(snap).get("fallback_min_pass", 0.15))


def fallback_ready(snap: Snapshot, months: int) -> bool:
    """连续 months 个月没有法律可推后，才允许降门槛兜底。"""
    return months >= fallback_threshold(snap)


def _need(opt: LawOption, p: dict, fallback: bool) -> float:
    if fallback:
        return float(p.get("fallback_min_pass", 0.15))
    override = (p.get("law_min_pass") or {}).get(opt.key)
    return float(override) if override is not None else float(p["min_pass"])


def _chance_ok(opt: LawOption, p: dict, fallback: bool) -> bool:
    """正常门槛是 min_pass；law_min_pass 可对关键法单独降门槛（如农本 30%）；
    兜底法再用 fallback_min_pass。0% 的法永远不推。"""
    chance = pass_chance(opt)
    if chance >= _need(opt, p, False):
        return True
    if not fallback:
        return False
    return opt.key in set(p.get("fallback_laws") or ()) and chance >= _need(opt, p, True)


def targets(snap: Snapshot | None = None) -> list[tuple[str, str]]:
    """法律路线：优先用国家专属路线（strategy.json 的 country_profiles）。"""
    route = cfg()["law_route"] if snap is None else strategy_config.law_route(snap)
    return [(g, law) for g, law in route]


def guard_fragile_unity(targets: list[tuple[str, str]], points: int | None) -> list[tuple[str, str]]:
    """攻略：脆弱的统一 ≤1 点时不要碰政体/权力分配（君主制或法团国家的改动会再 −1，
    直接进军阀时代）。distribution_of_power 与 governance_principles 都跳过。"""
    if points is not None and points <= 1:
        banned = {"lawgroup_distribution_of_power", "lawgroup_governance_principles"}
        return [(g, law) for g, law in targets if g not in banned]
    return targets


def candidates(snap: Snapshot, options: list[LawOption], enacting: str | None,
               fallback: bool = False) -> list[Decision]:
    """可推、且通过率达标的路线法律。fallback=True 时，关键法门槛降到 fallback_min_pass。"""
    if enacting:
        return []
    p = _pcfg(snap)
    out: list[Decision] = []
    for opt in options:
        current = snap.laws.get(opt.group)
        if current is None or current.key == opt.key or not opt.valid:
            continue
        chance = pass_chance(opt)
        if not _chance_ok(opt, p, fallback):
            continue
        tag = "（兜底）" if chance < float(p["min_pass"]) else ""
        out.append(Decision("enact_law", {"law": opt.key},
                            f"{opt.group}：{current.name} → {opt.name}，预计通过率 {chance:.0%}{tag}", chance))
    if fallback:
        # 正常法律先走；兜底法律按 fallback_laws 的顺序（农本主义优先）
        order = {k: i for i, k in enumerate(p.get("fallback_laws") or ())}
        out.sort(key=lambda d: (d.score < float(p["min_pass"]), order.get(d.args["law"], 999)))
    return out


def reform(snap: Snapshot, options: list[LawOption], enacting: str | None,
           fallback: bool = False) -> Decision | None:
    """路线上排在最前、只差支持者的目标：拉一个支持它的在野集团进政府。
    合法性太低（游戏提示“非法政府”）时，先移除影响力最小的在朝集团，别再加人。"""
    p = _pcfg(snap)
    if not snap.igs:
        return None
    # 立法进行中也可以改组政府（实测游戏允许），但不要另起一条法律；
    # 这里只做超限/合法性修复，options 为空时自然不会加支持者。
    gov = [ig for ig in snap.igs if ig.in_gov]
    legit = snap.country.get("legitimacy") or 0.0
    limit = _gov_limit(snap, p)
    protected = {p.get("ruler_ig") or ""} | set(p.get("protected_igs") or ())
    removable = [ig for ig in gov if ig.name not in protected]
    # 独裁制上限 1（总 2）：多一个集团就 −20 合法性，且意识形态惩罚 ×1.6
    if len(gov) > limit and removable:
        smallest = min(removable, key=lambda ig: ig.clout)
        members = sorted(ig.index for ig in gov if ig.index != smallest.index)
        return Decision("reform_government", {"members": members, "add": f"移除{smallest.name}"},
                        f"政府 {len(gov)} 个集团超过上限 {limit}（{smallest.name} 影响力 "
                        f"{smallest.clout:.0%}），规模惩罚会压低合法性", score=-smallest.clout)
    if legit < p.get("min_legitimacy_recover", 50) and len(gov) > 1 and removable:
        smallest = min(removable, key=lambda ig: ig.clout)
        members = sorted(ig.index for ig in gov if ig.index != smallest.index)
        return Decision("reform_government", {"members": members, "add": f"移除{smallest.name}"},
                        f"合法性 {legit:.0f} 过低（非法政府），移除影响力最小的在朝集团 "
                        f"{smallest.name}（{smallest.clout:.0%}）", score=-smallest.clout)
    if candidates(snap, options, None, fallback):
        return None
    if len(gov) >= limit or legit < p["min_legitimacy_to_add"]:
        return None
    for opt in options:
        if not (opt.support_only or (opt.valid and not _chance_ok(opt, p, fallback))):
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
