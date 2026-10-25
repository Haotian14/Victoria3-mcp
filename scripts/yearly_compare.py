"""Generate yearly snapshots from logs/runs.jsonl for comparison with the UP table.

Usage:
    python scripts/yearly_compare.py --label v6-timeline-300m
    python scripts/yearly_compare.py --label v6-120m --out docs/v6_yearly.md

The run history is monthly; for each Gregorian year we pick the latest month
available (usually December).  1861 in a 300-month run only has January, so the
output warns when the last year is partial.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_RUNS = Path("logs/runs.jsonl")


def _load(path: Path) -> list[dict]:
    out: list[dict] = []
    for line in path.read_bytes().decode("utf-8", "replace").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _pick(runs: list[dict], label: str) -> dict:
    matches = [r for r in runs if str(r.get("label") or "") == label]
    if not matches:
        labels = sorted({str(r.get("label") or "") for r in runs})[-12:]
        raise SystemExit(f"label not found: {label}\nrecent labels: {labels}")
    return matches[-1]


def _date(value: str) -> tuple[int, int, int]:
    y, m, d = (int(x) for x in str(value).split("."))
    return y, m, d


def _yearly(history: list[dict]) -> dict[int, tuple[int, int, dict]]:
    """year -> (month, day, latest snapshot in that year)."""
    out: dict[int, tuple[int, int, dict]] = {}
    for row in history:
        try:
            y, m, d = _date(row["date"])
        except (KeyError, ValueError):
            continue
        if y not in out or (m, d) > (out[y][0], out[y][1]):
            out[y] = (m, d, row)
    return out


def _m(value: object) -> str:
    try:
        return f"{float(value) / 1e6:,.1f}M"  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "?"


def _k(value: object) -> str:
    try:
        return f"{float(value) / 1e3:+,.1f}K"  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "?"


def _pct(value: object) -> str:
    try:
        return f"{float(value) * 100:.1f}%"  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "?"


def _num(value: object, digits: int = 1) -> str:
    try:
        return f"{float(value):,.{digits}f}"  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "?"


def render(label: str, run: dict) -> str:
    history = run.get("history") or []
    if not history:
        raise SystemExit(f"run has no history: {label}")
    rows = _yearly(history)
    years = sorted(rows)
    lines = [
        f"# v6 年度快照：{label}",
        "",
        f"- 运行区间：{run.get('start')} → {run.get('end')}（{run.get('months')} 个月）",
        "- 采用口径：每年最后一个有记录的月份；不是 12-31 的精确年末。",
        "",
        "| 年份 | 采用日期 | 建造力(已用/上限) | GDP | 识字率 | SoL | 人口 | 人均 GDP | 国库 | 周结余 | 法律组数 |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for y in years:
        m, d, row = rows[y]
        gdp = row.get("gdp")
        pop = row.get("population")
        per = row.get("gdp_per_capita")
        if per is None and gdp and pop:
            per = float(gdp) / float(pop)
        lines.append(
            f"| {y} | {y}-{m:02d}-{d:02d} | "
            f"{_num(row.get('construction_used'), 0)}/{_num(row.get('construction'), 0)} | "
            f"{_m(gdp)} | {_pct(row.get('literacy'))} | {_num(row.get('sol'), 2)} | "
            f"{_m(pop)} | {_num(per, 3)} | {_m(row.get('money'))} | "
            f"{_k(row.get('balance'))} | {_num(row.get('laws'), 0)} |"
        )
    last = years[-1]
    if rows[last][0] < 12:
        lines += [
            "",
            f"> ⚠️ {last} 年只有 {rows[last][0]} 月的数据，不能和 UP 的年末读数直接比；"
            f"如果要按年对年，等跑到 {last + 1} 年或改用同月对比。",
        ]
    lines += [
        "",
        "> 建造力是 `used/cap`（总已用/基础），不是“等级”；政府/私营分项另记。GDP/人口单位 M，国库 M，周结余 K。人均GDP直接按GDP/人口计算，两边须统一单位。",
        "> 与 `docs/up_yearly.md` 并排看；优先比建造力、GDP、人均 GDP、SoL、识字率、国库。",
        "> 法律组数是观测到的现行法律组数量，不是本局通过的改革条数；生效时间另按制定记录及真实现行法核验。",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="", help="run label；默认取 runs.jsonl 最后一条")
    ap.add_argument("--runs", default=str(DEFAULT_RUNS))
    ap.add_argument("--out", default="", help="写到 Markdown 文件；默认打印")
    args = ap.parse_args()
    runs = _load(Path(args.runs))
    if not runs:
        raise SystemExit(f"no runs in {args.runs}")
    label = args.label or str(runs[-1].get("label") or "latest")
    text = render(label, _pick(runs, label))
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
