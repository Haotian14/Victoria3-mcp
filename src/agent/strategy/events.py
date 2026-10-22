"""事件选项：先避免灾难，再按效果关键词挑收益最大的选项。

事件接口来自 actions.Actions.events()：title / text / desc（EventOption.GetDesc，游戏按效果生成的
tooltip）。这里不读存档、不改游戏，只给 runner 一个确定性的选择：
- 鸦片战争：没有军队 / 外交自动化时默认让步（country_profiles.CHI.opium_war = avoid），
  避免 1836 年被英国打崩；想打就把它改成 fight；
- 立法检查点：优先推进 / 通过，别选辩论拖延；
- 其他：按 desc 里的「增加 / 减少 + 好/坏名词」逐句打分，默认选项只加半分。
"""

from __future__ import annotations

import re
from typing import Any

from agent.strategy.config import profile_for_tag

# 效果词（desc 是本地化文本，中英文都匹配）
GOOD = {
    "创新": 4, "研究": 4, "科技": 3, "识字": 4, "教育": 3, "大学": 2,
    "生活水平": 3, "合法性": 3, "忠诚": 2, "稳定": 2, "秩序": 2,
    "基础设施": 2, "建造力": 3, "建造部门": 2, "投资": 2,
    "工业化": 3, "现代化": 3, "征税能力": 3, "税收": 2, "收入": 1,
    "贸易": 1, "承认": 4, "威望": 1, "人口": 1, "生产率": 2,
    "吞吐": 2, "产值": 2, "市场": 1, "关系": 1, "防御同盟": 3, "同盟": 2,
    "条约": 1, "殖民地": 1, "公司": 1, "创新率": 4,
    "innovation": 4, "research": 4, "literacy": 4, "education": 3,
    "standard of living": 3, "legitimacy": 3, "loyalist": 2, "infrastructure": 2,
    "construction": 3, "investment": 2, "industrialization": 3, "tax capacity": 3,
}
BAD = {
    "战争": 5, "开战": 6, "宣战": 6, "敌对": 2, "冲突": 2,
    "叛乱": 4, "革命": 4, "激进": 3, "动乱": 3, "骚乱": 3,
    "债务": 3, "借债": 3, "破产": 6, "赔款": 3, "割让": 4,
    "屈服": 2, "投降": 5, "禁止": 1, "关闭": 1, "拒绝": 1,
    "刑罚": 2, "处决": 3, "流放": 2, "恶名": 2, "腐败": 2, "歧视": 2,
    "war": 5, "radical": 3, "debt": 3, "bankrupt": 6, "reparations": 3,
}
REDUCE = ("减少", "降低", "失去", "削减", "下降", "恶化", "decrease", "reduce", "lose")
INCREASE = ("增加", "提高", "提升", "获得", "增长", "上升", "改善", "加强", "increase", "gain", "improve")
LAW_ADVANCE = ("推进", "通过", "成功", "支持", "advance", "pass", "success")
LAW_STALL = ("辩论", "搁置", "拖延", "受阻", "妥协", "debate", "stall", "delay")

_TAG = re.compile(r"#\w+|@\w+!|§[A-Za-z0-9]|\$[^$]*\$")


def _clean(text: str) -> str:
    return _TAG.sub(" ", text or "").replace("\\n", " ").replace("#n", " ")


def _clause_score(clause: str) -> float:
    low = clause.lower()
    good = sum(w for k, w in GOOD.items() if k in low)
    bad = sum(w for k, w in BAD.items() if k in low)
    sign = 1
    if any(v in low for v in REDUCE):
        sign = -1
    elif any(v in low for v in INCREASE):
        sign = 1
    return (good - bad) * sign


def score(event: dict[str, Any], option: dict[str, Any]) -> float:
    text = _clean(option.get("text", "") + " " + option.get("desc", ""))
    total = sum(_clause_score(c) for c in re.split(r"[。；;，,\n]", text) if c.strip())
    if option.get("default"):
        total += 0.5
    return total


def pick(event: dict[str, Any], tag: str = "") -> int | None:
    """返回要选的选项下标；没有可用选项时返回 None。tag 用于取国家档案（如 CHI 的鸦片策略）。"""
    opts = [o for o in event.get("options", []) if o.get("enabled")]
    if not opts:
        return None
    key = event.get("key") or ""

    # 鸦片战争：没有军队 / 外交自动化时，选最后一个（“让步 / 不感兴趣”），避免开战。
    if key.startswith(("opium_wars.1", "opium_wars.2")):
        mode = profile_for_tag(tag).get("opium_war", "avoid")
        if mode == "avoid":
            return max(opts, key=lambda o: o["option"])["option"]

    # 立法检查点：优先推进 / 通过，别选辩论拖延（选错会拖慢甚至拖失败）。
    if "law" in key.lower() or "enact" in key.lower():
        advance = [o for o in opts
                   if any(w in _clean(o.get("text", "") + o.get("desc", "")) for w in LAW_ADVANCE)]
        if advance:
            return max(advance, key=lambda o: score(event, o))["option"]

    best = max(opts, key=lambda o: (score(event, o), o.get("default", False), -o["option"]))
    return best["option"]
