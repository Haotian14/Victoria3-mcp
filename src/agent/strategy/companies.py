"""公司：corporate_charters 后，按“同州 5 级”创建资本家类公司。

1.13 调研（docs/research-progress.md #5）：
- 公司槽要 `corporate_charters` 才有（之前 GetMaxNumCompanies=0）；
- 可建立列表 `GetAvailableCompanies` 由游戏按 `possible` 过滤，5 级同州建筑已经算在内；
- 只选没有 `category` 的 basic 公司（默认资本家所有），避免给士大夫/官僚/地主加 clout；
- 纺织/纸张/钢优先，其次家居/食品/金属制品/林业/金属矿。每月最多建 1 家。
"""

from __future__ import annotations

from agent.observe import Snapshot
from agent.strategy.config import Decision, profile

PREFERRED = (
    "company_basic_textiles",
    "company_basic_paper",
    "company_basic_steel",
    "company_basic_home_goods",
    "company_basic_food",
    "company_basic_metalworks",
    "company_basic_forestry",
    "company_basic_metal_mining",
)


def candidates(snap: Snapshot) -> list[Decision]:
    spec = profile(snap).get("companies") or {}
    max_per_month = int(spec.get("max_per_month", 1))
    if snap.companies is None:
        return []
    existing = set(snap.companies.existing)
    available = [k for k in snap.companies.available if k not in existing]
    # 攻略：纸张/建设公司是过渡，钢框架后要换掉。年份到了、后继公司在可建立列表里、
    # 旧公司还在 → 先解散腾槽，下个月再建后继公司。
    replace_after = int(spec.get("replace_after_year", 0) or 0)
    replace = spec.get("replace") or {}
    if replace_after and snap.date.year >= replace_after:
        for old, new in replace.items():
            if old in existing and (new in available or new in existing):
                return [Decision("company", {"key": old, "create": False},
                                 f"解散过渡公司 {old}（{snap.date.year} 年，准备换 {new}）")]
    slots = int(snap.country.get("max_companies") or 0) - int(snap.country.get("num_companies") or 0)
    if slots <= 0:
        return []
    preferred = list(spec.get("preferred") or PREFERRED)
    out: list[Decision] = []
    for key in preferred:
        if key not in available:
            continue
        out.append(Decision("company", {"key": key, "create": True},
                            f"创建资本家公司 {key}（同州 5 级已满足，公司槽 {slots} 个空位）",
                            score=float(max_per_month - len(out))))
        if len(out) >= max_per_month:
            break
    return out
