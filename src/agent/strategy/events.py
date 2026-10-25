"""事件选项：先避免灾难，再按效果关键词挑收益最大的选项。

事件接口来自 actions.Actions.events()：title / text / desc（EventOption.GetDesc，游戏按效果生成的
tooltip）。这里不读存档、不改游戏，只给 runner 一个确定性的选择：
- 鸦片战争：没有军队 / 外交自动化时默认让步（country_profiles.CHI.opium_war = avoid），
  避免 1836 年被英国打崩；想打就把它改成 fight；
- 立法检查点：优先推进 / 通过，别选辩论拖延；
- 其他：按 desc 里的「增加 / 减少 + 好/坏名词」逐句打分，默认选项只加 0.1 分。

1.13.11 事件链调研（docs/research-progress.md #14）：大清的关键事件默认选项经常是坑
（boxer.4.a、heavenly.5.a、CHI_missionaries.3/4.b、famine_political.1.b 等），
GetDesc 又看不到 hidden_effect / set_variable，所以对政权级事件按「事件键 + 选项关键词」硬编码，
默认只作 fallback；通用关键词打分继续兜底其余事件。
"""

from __future__ import annotations

import re
from typing import Any

from agent.strategy.config import profile_for_tag
from agent.strategy import budget
from agent.observe import Snapshot

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

# 事件键 → (优先选项关键词, fallback)。fallback 取 "default" 或 "first"。
# 只列「默认/关键词会选错、后果到政权级」的事件；其余仍走通用打分。
HARD: dict[str, tuple[tuple[str, ...], str]] = {
    "unable_to_enact.1": (("彻底改写", "rewrite"), "default"),
    "boxer_rebellion_events.1": (("盲从", "愚妄"), "default"),          # a：所有汉人家园国 -100 关系
    "boxer_rebellion_events.2": (("团结", "正义", "united"), "default"),
    "boxer_rebellion_events.3": (("这些屈辱",), "default"),            # b：改朝换代、杀统治者
    "boxer_rebellion_events.4": (("和解", "大局为重"), "default"),      # a：-1 统一、移除满族
    "heavenly.4": (("碾碎",), "default"),                             # b：play as 太平天国
    "heavenly.5": (("仁慈", "赦免"), "default"),                      # a：基督教列强 -25 关系
    "heavenly.1": (("拒绝",), "default"),                             # a：+5% 转化，加速太平天国
    "CHI_missionaries.1": ((), "default"),                            # b 比 a 更轻
    "CHI_missionaries.2": (("处决",), "default"),                     # a：该州 10 年不再触发
    "CHI_missionaries.3": (("欢迎",), "default"),                     # b：+25% 转化 + 激进
    "CHI_missionaries.4": (("欢迎",), "default"),
    "warlord_china_events.100": (("挽救",), "default"),               # 其他选项放弃大清
    "warlord_china_events.101": (("重建",), "default"),               # b：+官僚/权威/合法性
    "warlord_china_events.110": (("掩盖", "掩盖此事"), "default"),
    "warlord_china_events.200": (("聪明才智",), "default"),           # b：+25% 研究
    "warlord_china_events.301": (("毫无意义",), "default"),           # a 只有 40–66.7% 成功
    "famine_political.1": (("生命",), "default"),                     # b：0.3 下层激进
    "famine_events.3": (("紧急救济",), "default"),                    # 无 relief 时 c 严格优于 b
    "famine_events.4": (("接受",), "default"),                        # a/b：+2 生活水平
    "treaty_port_inheritance_events.1": (("遵守协议",), "default"),
    "strike.1": (("谈判",), "default"),
    "strike.4": (("破坏罢工", "替代工人"), "default"),
    "1848.2": (("清除",), "default"),
    "opium_wars.3": (("主权", "绝对"), "default"),       # A：china_authority；B 是福利路线
    "opium_wars.6": (("处决",), "default"),
    "opium_wars.7": (("卫生", "健康", "医疗"), "default"),
    "negotiation.1": (("修正案", "amendment"), "default"),
    "historical_agitators.21": (("留下", "留在中国", "不要流放", "赦免"), "default"),
}

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
        total += 0.1                # 只作平手裁决；默认选项经常是坑
    return total


def _blob(option: dict[str, Any]) -> str:
    return _clean(option.get("text", "") + " " + option.get("desc", ""))


def _hard_pick(opts: list[dict[str, Any]], keywords: tuple[str, ...], fallback: str) -> int:
    if keywords:
        for o in opts:
            if any(k.lower() in _blob(o).lower() for k in keywords):
                return o["option"]
    if fallback == "default":
        return next((o["option"] for o in opts if o.get("default")), opts[0]["option"])
    return opts[0]["option"]


def fiscal_option_allowed(option: dict[str, Any], snap: Snapshot,
                          fragile_unity: int | None = None) -> bool:
    raw = str(option.get("text", "")) + " " + str(option.get("desc", ""))
    text = _clean(raw).lower()
    # 无需贷款来换任何事件收益；减债/减少革命风险的选项仍允许。
    for clause in re.split(r"[。；;\n]", text):
        debt = any(w in clause for w in ("借款", "借债", "贷款", "take loan"))
        reducing_debt = re.search(r"(?:偿还|归还|减少|降低|清偿|拒绝|避免|停止|repay|reduce).{0,8}(?:贷款|债务|借款|借债|loan|debt)", clause)
        if debt and not reducing_debt:
            return False
        if any(w in clause for w in ("宣告破产", "债务违约", "declare bankruptcy")):
            return False
        if fragile_unity is not None and fragile_unity <= 4 and any(
                w in clause for w in ("发动革命", "支持革命", "加入革命", "start revolution", "play as")):
            return False
    # 带货币效果且是支出时按金额预留；读不出金额则禁止，避免默认选项静默借款。
    cost = 0.0
    for clause in re.split(r"[。；;\n]", raw):
        monetary = any(w in clause.lower() for w in ("money", "£", "金钱", "国库"))
        negative = any(w in clause.lower() for w in ("支付", "花费", "支出", "失去", "减少", "pay", "spend", "lose"))
        negative |= bool(re.search(r"[-−]\s*[\d£]", _clean(clause)))
        if monetary and negative:
            nums = re.findall(r"(?:\d[\d,]*(?:\.\d+)?)[KMB]?", re.sub(r"[\x15\x16][^ !]*!", " ", _clean(clause)), re.I)
            if not nums:
                return False
            amounts = []
            for num in nums:
                mult = {"k": 1e3, "m": 1e6, "b": 1e9}.get(num[-1].lower(), 1)
                amounts.append(float((num[:-1] if mult > 1 else num).replace(",", "")) * mult)
            cost += max(amounts)
    weekly = any(w in text for w in ("每周", "weekly", "per week"))
    return not cost or budget.can_spend(snap, weekly=cost if weekly else 0, upfront=0 if weekly else cost)


def pick(event: dict[str, Any], tag: str = "", snap: Snapshot | None = None,
         fragile_unity: int | None = None) -> int | None:
    """返回要选的选项下标；没有可用选项时返回 None。tag 用于取国家档案（如 CHI 的鸦片策略）。"""
    opts = [o for o in event.get("options", []) if o.get("enabled")]
    if snap is not None:
        opts = [o for o in opts if fiscal_option_allowed(o, snap, fragile_unity)]
    if not opts:
        return None
    key = event.get("key") or ""

    # 鸦片战争：没有军队 / 外交自动化时，选“让步 / 不能得罪”，避免开战。
    if key.startswith(("opium_wars.1", "opium_wars.2")):
        mode = profile_for_tag(tag).get("opium_war", "avoid")
        if mode == "avoid":
            for o in opts:
                if any(k in _blob(o) for k in ("不能得罪", "让步", "妥协", "不感兴趣", "give in")):
                    return o["option"]
            return max(opts, key=lambda o: o["option"])["option"]

    # 政权级事件：按事件键硬编码，优先于通用打分
    hard = HARD.get(key)
    if hard:
        return _hard_pick(opts, *hard)

    # 立法检查点：优先推进 / 通过，别选辩论拖延（选错会拖慢甚至拖失败）。
    if "law" in key.lower() or "enact" in key.lower():
        advance = [o for o in opts
                   if any(w in _clean(o.get("text", "") + o.get("desc", "")) for w in LAW_ADVANCE)]
        if advance:
            return max(advance, key=lambda o: score(event, o))["option"]

    best = max(opts, key=lambda o: (score(event, o), o.get("default", False), -o["option"]))
    return best["option"]
