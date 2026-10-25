"""按月/周证据生成财政护栏诊断；缺失证据不判作达标。"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from yearly_compare import _load, _pick, _yearly


def render(run: dict) -> str:
    rows = run.get("fiscal_history") or []
    monthly = run.get("history") or []
    years = _yearly(monthly)
    dates = sorted({date(*map(int, r['date'].split('.'))) for r in rows})
    gap = max(((b - a).days for a, b in zip(dates, dates[1:])), default=0)
    def outcome(ok: bool | None) -> str:
        return "证据不足" if ok is None else "通过" if ok else "未通过"
    def value(row: dict, key: str) -> float | None:
        v = row.get(key)
        return float(v) if v is not None else None
    def threshold(year: int, key: str, minimum: float) -> tuple[str, str]:
        row = years.get(year, (0, 0, {}))[2]
        v = value(row, key)
        return outcome(None if v is None else v >= minimum), "?" if v is None else f"{v:,.2f}（{row['date']}）"
    cash = [r["money"] for r in rows if r.get("money") is not None]
    complete = bool(run.get("months", 0) >= 120 and str(run.get("end", "")).startswith("1846."))
    floor = min(cash) if cash else None
    default = any(r.get("in_default") or r.get("bankrupt") for r in rows)
    loans = any(r.get("loan_penalty") for r in rows)
    trace_complete = bool(rows and all(r.get("in_default") is not None and r.get("bankrupt") is not None
                                      and r.get("loan_penalty") is not None for r in rows))
    recognised = [r for r in rows if r.get("rank_name") and
                  "未受认可" not in r["rank_name"] and "unrecognized" not in r["rank_name"].lower()]
    first_recognised = recognised[0]["date"] if recognised else None
    by_1843 = bool(first_recognised and int(first_recognised.split(".")[0]) <= 1843)
    # 独立统计月初没有立法的连续月份，避免政府改组把策略计数清零而掩盖空窗。
    stall = consecutive = 0
    for row in rows:
        if row.get("cadence") != "monthly":
            continue
        consecutive = 0 if row.get("enacting") else consecutive + 1
        stall = max(stall, consecutive)
    lines = [f"# 财政护栏诊断：{run.get('label')}", "",
             f"- 区间：{run.get('start')} → {run.get('end')}，{run.get('months')} 个月；{run.get('stopped')}。",
             f"- 财政样本 {len(rows)} 条（按周巡检，实际相邻观测日期最大间隔{gap}天）；月度/终点快照 {len(monthly)} 条。",
             "- `institutions` 单位是官僚点；机构没有独立货币支出项，其现金成本归入政府工资/商品，不能重复加总。", "",
             "| 验收项 | 结果 | 实测 |", "|---|---|---|",
             f"| 完成120个月 | {outcome(complete)} | {run.get('months')}个月 |",
             f"| 国库从不见底 | {outcome(None if not complete or floor is None else floor > 0)} | 最低 £{floor:,.0f} |" if floor is not None else "| 国库从不见底 | 证据不足 | ? |",
             f"| 无财政违约/破产 | {outcome(False if default else True if complete and trace_complete else None)} | in_default/破产标记样本中{'有' if default else '无'} |",
             f"| 不触发借款统一惩罚 | {outcome(False if loans else True if complete and trace_complete else None)} | china_warlord_explosion_loans={'1' if loans else '0'} |"]
    for year, target in ((1838, 200), (1843, 250)):
        row = years.get(year, (0, 0, {}))[2]
        used, cap = value(row, 'construction_used'), value(row, 'construction')
        if used is None or cap is None:
            lines.append(f"| {year}建造力≥{target} | 证据不足 | ? |")
        else:
            verdict = "通过" if used >= target and cap >= target else "上限通过、已用未达" if cap >= target else "未通过"
            lines.append(f"| {year}建造力≥{target} | {verdict} | 已用/上限 {used:,.0f}/{cap:,.0f}（{row['date']}） |")
    for year, key, target, label in ((1843, "sol", 8, "1843 SoL≥8.0"),
                                    (1843, "gdp", 120_000_000, "1843 GDP≥120M")):
        passed, measured = threshold(year, key, target)
        lines.append(f"| {label} | {passed} | {measured} |")
    lines += [f"| 1843年底前受认可 | {outcome(by_1843 if complete or first_recognised else None)} | {first_recognised or '未观测到'} |",
              f"| 无立法空窗≤6个月 | {outcome(stall <= 6 if complete else None)} | 最长 {stall} 个月 |", "",
              "法律空窗按月初是否有正在推进的法律独立统计，不因政府改组而清零；不把法律本身推进缓慢算作空窗。日期按每年最后一个月度样本，保持与 yearly_compare 一致。此处违约仅指财政in_default，条约条款未履约另行核对。",
              "\n| 年份 | 国库最低 | 利息最高/周 | 军费/周 | 补贴/周 | 建造商品/周 | 机构官僚 | 军队总数（含预备） | 借款标记 |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    for year in sorted(years):
        yr = [r for r in rows if str(r.get("date", "")).startswith(f"{year}.")]
        if not yr:
            continue
        last = yr[-1]
        def n(key: str, extreme=None):
            vals = [r[key] for r in yr if r.get(key) is not None]
            v = extreme(vals) if vals and extreme else last.get(key)
            return "?" if v is None else f"{v:,.0f}"
        lines.append(f"| {year} | {n('money', min)} | {n('interest', max)} | {n('military')} | {n('subsidies')} | "
                     f"{n('construction_goods')} | {n('institutions')} | {n('army_size')} | {last.get('loan_penalty')} |")
    lines += ["", "## 年度预算流量", "",
              "采用每年最后一个月度样本，与年度快照同日。金额单位K/周，信用额度单位M；政府建造商品已包含在总建造商品中，不重复相加。",
              "机构官僚不是货币支出；军队总数包括预备征召，不能当成全部动员的常备军。", "",
              "| 年份 | 日期 | 收入 | 支出 | 结余 | 政府工资 | 政府商品 | 政府建造商品 | 军费 | 补贴 | 利息 | 剩余信用M |",
              "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for year, (_, _, row) in sorted(years.items()):
        def k(key: str, unit: float = 1000) -> str:
            v = value(row, key)
            return "?" if v is None else f"{v / unit:,.1f}"
        fields = [k(key) for key in ("income", "expenses", "balance", "government_wages",
                                    "government_goods", "government_construction_goods", "military",
                                    "subsidies", "interest")]
        lines.append(f"| {year} | {row['date']} | " + " | ".join(fields) + f" | {k('credit_left', 1e6)} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    run = _pick(_load(Path("logs/runs.jsonl")), args.label)
    Path(args.out).write_text(render(run), encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
