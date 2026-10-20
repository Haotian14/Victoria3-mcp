"""汇总 logs/runs.jsonl：同一国家的策略局与基线局，在 1 / 5 / 10 年时的指标对比。

    python scripts/compare_runs.py              # 每个 label 取最近一局
    python scripts/compare_runs.py --all        # 列出全部局
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
RUNS = os.path.join(ROOT, "logs", "runs.jsonl")
KEYS = ("gdp", "money", "construction", "sol", "literacy", "population")


def at_month(run: dict, m: int) -> dict | None:
    h = run.get("history") or []
    return h[m] if m < len(h) else None


def fmt(v) -> str:
    if v is None:
        return "-"
    if abs(v) >= 1e6:
        return f"{v / 1e6:,.1f}M"
    if abs(v) >= 1e3:
        return f"{v / 1e3:,.1f}K"
    return f"{v:,.2f}"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    if not os.path.isfile(RUNS):
        print("还没有 logs/runs.jsonl")
        return 1
    runs = [json.loads(line) for line in open(RUNS, encoding="utf-8") if line.strip()]
    if not args.all:
        latest: dict[str, dict] = {}
        for r in runs:
            latest[r.get("label", "")] = r
        runs = list(latest.values())
    for r in runs:
        print(f"\n== {r.get('label')} {r.get('country')} {r.get('start')} → {r.get('end')}"
              f"（{r.get('months')} 个月，{r.get('seconds')} 秒）{r.get('stopped')}")
        print("   " + "".join(f"{k:>12}" for k in ("月份",) + KEYS))
        for m in (0, 12, 60, 120):
            row = at_month(r, m)
            if row:
                print("   " + f"{m:>12}" + "".join(f"{fmt(row.get(k)):>12}" for k in KEYS))
        if r.get("actions"):
            print(f"   动作 {r['actions']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
