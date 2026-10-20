"""里程碑 2 验收：从 1836.1.1 的存档自动跑到 1836.3.1，产出存档，state.py 读出新的日期。

    python scripts/check_clock.py [--save v3mcp_start_1836] [--to 1836.3.1]

会重启游戏。开局存档 v3mcp_start_1836.v3 是 1836.1.1 大清，放在存档目录里（复制自 autosave_exit）。
"""

from __future__ import annotations

import argparse
import glob
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from agent import gamedata, paths, save, state  # noqa: E402
from agent.bridge import Bridge  # noqa: E402
from agent.game import Clock, Date, launch, wait_in_game  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", default="v3mcp_start_1836")
    ap.add_argument("--to", default="1836.3.1")
    args = ap.parse_args()
    target = Date.parse(args.to)

    print(f"[1] 启动并载入 {args.save}")
    launch(save=args.save, restart=True, autosave="monthly")
    b = Bridge()
    wait_in_game(b)
    clock = Clock(b)
    clock.pause()
    start = clock.date()
    print(f"    当前日期 {start}")

    print(f"[2] 推进到 {target}")
    t0 = time.time()
    reached = clock.run_until(target)
    print(f"    停在 {reached}（{time.time() - t0:.0f} 秒）")
    if reached < target:
        print("失败：没有走到目标日期")
        return 1

    print("[3] 等自动存档")
    found = None
    deadline = time.time() + 120
    while time.time() < deadline and not found:
        for p in glob.glob(os.path.join(paths.save_dir(), "autosave*.v3")):
            if os.path.getmtime(p) < t0:
                continue
            meta = save.peek_meta(p)
            if "game_date" in meta and Date.parse(meta["game_date"]) >= target:
                size = -1
                while size != os.path.getsize(p):   # 等写完
                    size = os.path.getsize(p)
                    time.sleep(1.5)
                found = p
                break
        time.sleep(1)
    if not found:
        print("失败：没有等到目标日期之后的存档")
        return 1
    print(f"    {found}")

    print("[4] state.py 解析")
    cs = state.extract(state.load_gamestate(found), gamedata.get())
    print(f"    存档日期 {cs.date}，国家 {cs.tag}，国库 {cs.money}")
    ok = Date.parse(cs.date) >= target
    print("通过" if ok else "失败：存档日期不对")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
