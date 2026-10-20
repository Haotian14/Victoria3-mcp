"""命令行入口：按策略玩若干个月，或跑不干预的基线。

    python scripts/play.py --months 12                         # 接着当前局面玩一年
    python scripts/play.py --save v3mcp_start_1836 --months 120 # 重开 1836 开局，玩十年
    python scripts/play.py --save v3mcp_start_1836 --tag PRU --months 120   # 换成普鲁士
    python scripts/play.py --save v3mcp_start_1836 --baseline --months 120  # 基线：不做任何动作
    python scripts/play.py --advise                             # 只看本月计划，不执行

每局在 logs/runs.jsonl 追加一行（GDP、国库、建造力、生活水平的逐月记录与动作统计）。
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from agent import runner  # noqa: E402
from agent.bridge import Bridge  # noqa: E402
from agent.game import Clock, launch, wait_in_game  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=12)
    ap.add_argument("--save", default="", help="先重启游戏并载入这个存档（不带 .v3）")
    ap.add_argument("--tag", default="", help="载入后用控制台 tag 命令换成这个国家")
    ap.add_argument("--baseline", action="store_true", help="不做任何动作，只记录")
    ap.add_argument("--advise", action="store_true", help="只打印本月计划")
    ap.add_argument("--label", default="")
    args = ap.parse_args()

    b = Bridge()
    if args.save:
        print(f"重启游戏并载入 {args.save} ……")
        launch(save=args.save, restart=True, autosave="yearly")
    wait_in_game(b)
    Clock(b).pause()
    if args.tag:
        r = b.console(f"tag {args.tag}")
        print(f"tag {args.tag}：{r.get('output') or r.get('ok')}")

    if args.advise:
        snap, plan = runner.advise(b)
        print(f"[{snap.date}] {snap.name}")
        for line in plan.summary(10):
            print(" ", line)
        return 0

    label = args.label or ("baseline" if args.baseline else "strategy")
    if args.tag:
        label += f":{args.tag}"
    s = runner.play(b, args.months, verbose=print, label=label, act=not args.baseline)
    sm, em = s["start_metrics"] or {}, s["end_metrics"] or {}
    print(f"\n{s['country']} {s['start']} → {s['end']}（{s['months']} 个月，{s['seconds']} 秒）：{s['stopped']}")
    for k in ("gdp", "money", "construction", "sol", "literacy", "population"):
        print(f"  {k:13} {sm.get(k)} → {em.get(k)}")
    print(f"  动作 {s['actions']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
