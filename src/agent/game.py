"""游戏进程与时间：启动 / 重启（scripts/launch.ps1）、暂停、调速、推进到指定日期、存档。

时间全部走界面同一套数据函数（TimeKeeper.*），不按键、不看屏幕。
存档：游戏没有可直接调用的「立即存档」入口（PauseMenu.Save 只是打开存档窗口），
所以用游戏自带的每月自动存档（用户目录 pdx_settings.json 的 game.autosave），见 docs/bridge.md。
"""

from __future__ import annotations

import glob
import ctypes
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from typing import Callable

from agent import paths
from agent.bridge import Bridge, BridgeError, GameError

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
LAUNCH = os.path.join(ROOT, "scripts", "launch.ps1")

MAX_SPEED = 4          # TimeKeeper.SetGameSpeed 的下标 0..4，界面上显示为 1..5
AUTOSAVE_VALUES = ("never", "monthly", "quarteryear", "halfyear", "yearly", "five_year")


# ---------------------------------------------------------------- 日期

@dataclass(frozen=True, order=True)
class Date:
    year: int
    month: int
    day: int

    @classmethod
    def parse(cls, text: str) -> "Date":
        """'1836.3.1' / '1836-03-01' / 界面上的 '3月 10, 1836' / 'March 10, 1836'。"""
        t = text.strip()
        m = re.fullmatch(r"(\d{3,4})[.\-/](\d{1,2})[.\-/](\d{1,2})", t)
        if m:
            return cls(int(m[1]), int(m[2]), int(m[3]))
        m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2}),?\s*(\d{3,4})", t)
        if m:
            return cls(int(m[3]), int(m[1]), int(m[2]))
        m = re.search(r"([A-Za-z]+)\s+(\d{1,2}),?\s*(\d{3,4})", t)
        if m and m[1][:3].lower() in _MONTHS:
            return cls(int(m[3]), _MONTHS.index(m[1][:3].lower()) + 1, int(m[2]))
        raise ValueError(f"认不出的日期：{text!r}")

    def __str__(self) -> str:
        return f"{self.year}.{self.month}.{self.day}"

    def next_month(self) -> "Date":
        return Date(self.year + (self.month == 12), self.month % 12 + 1, 1)

    def months_since(self, other: "Date") -> int:
        return (self.year - other.year) * 12 + (self.month - other.month)


_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


# ---------------------------------------------------------------- 进程


def available_memory_gb() -> float:
    """Windows 的可用物理内存，避免 WMI 权限差异；不是空闲提交额度。"""
    class MemoryStatus(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
            (k, ctypes.c_ulonglong) for k in ("total", "available", "page_total", "page_available",
                                            "virtual_total", "virtual_available", "extended")]
    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise OSError("无法读取可用内存")
    return status.available / (1024 ** 3)

def running() -> bool:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq victoria3.exe", "/NH"],
                         capture_output=True, text=True, errors="replace").stdout
    return "victoria3.exe" in out.lower()


def set_autosave(value: str) -> bool:
    """改用户目录 pdx_settings.json 的自动存档频率。游戏运行时改了会被它退出时覆盖，所以只在未运行时改。
    返回是否改动了文件。"""
    if value not in AUTOSAVE_VALUES:
        raise ValueError(f"autosave 只能取 {AUTOSAVE_VALUES}")
    if running():
        raise RuntimeError("游戏在运行，pdx_settings.json 会在退出时被覆盖；先关游戏")
    path = os.path.join(paths.user_dir(), "pdx_settings.json")
    data = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
    game = data.setdefault("game", {})
    if game.get("autosave") == value:
        return False
    game["autosave"] = value
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent="\t")
    return True


def launch(save: str = "", restart: bool = False, autosave: str | None = "monthly",
           timeout: int = 300, notifications: bool = False) -> str:
    """启动游戏并注入桥接层（scripts/launch.ps1），返回脚本输出。save 为空时继续最近的存档。"""
    if restart and running():
        subprocess.run(["taskkill", "/IM", "victoria3.exe", "/F"], capture_output=True)
        for _ in range(60):
            if not running():
                break
            time.sleep(1)
        time.sleep(2)
    if autosave and not running():
        set_autosave(autosave)
    args = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", LAUNCH,
            "-TimeoutSec", str(timeout)]
    if save:
        args += ["-Save", save]
    if not notifications:
        args.append("-NoNotifications")   # 游戏的 -no_notifications：不弹窗、不自动暂停
    if running():
        args.append("-Attach")
    p = subprocess.run(args, capture_output=True, timeout=timeout + 60)
    out = (p.stdout + p.stderr).decode("gbk", errors="replace")
    if p.returncode != 0:
        raise RuntimeError(f"启动失败：{out.strip()[-500:]}")
    return out


def wait_in_game(bridge: Bridge, timeout: float = 300) -> None:
    """等到存档载入完毕（IsInGame）。桥接层就绪时游戏往往还在加载存档。"""
    t0 = time.time()
    last = None
    while time.time() - t0 < timeout:
        try:
            if bridge.read("[IsInGame]") == "1":
                return
        except (BridgeError, GameError) as exc:
            last = exc
        time.sleep(2)
    raise TimeoutError(f"{timeout} 秒内没有进入游戏（{last}）")


# ---------------------------------------------------------------- 时间

class Clock:
    def __init__(self, bridge: Bridge) -> None:
        self.b = bridge

    def date(self) -> Date:
        return Date.parse(self.b.read("[TimeKeeper.GetCurrentDate.GetString]"))

    def paused(self) -> bool:
        return self.b.read("[TimeKeeper.IsPaused]") == "1"

    def _set_paused(self, want: bool) -> None:
        if self.paused() == want:
            return
        self.b.exec("TimeKeeper.TogglePause")
        # IsPaused 要到下一帧才更新
        for _ in range(40):
            time.sleep(0.05)
            if self.paused() == want:
                return
        raise GameError(f"切换暂停后状态没变（想要 paused={want}）")

    def pause(self) -> None:
        self._set_paused(True)

    def resume(self) -> None:
        self._set_paused(False)

    def set_speed(self, speed: int = MAX_SPEED) -> None:
        self.b.exec(f"TimeKeeper.SetGameSpeed('(int32){max(0, min(MAX_SPEED, speed))}')")

    def run_until(self, target: Date, timeout: float = 600, poll: float = 0.1,
                  on_tick: Callable[[], None] | None = None, tick_interval: float = 1.0) -> Date:
        """以最高速推进到 target（含）后暂停，返回暂停时的日期。最高速约每秒 6 天，可能多走一两天。
        on_tick：每 tick_interval 秒调一次（runner 用它处理事件，避免被游戏按默认选项自动答掉）。"""
        now = self.date()
        if now >= target:
            return now
        self.set_speed(MAX_SPEED)
        self.resume()
        t0 = time.time()
        stalled = 0
        last_tick = t0
        try:
            while time.time() - t0 < timeout:
                time.sleep(poll)
                if on_tick is not None and time.time() - last_tick >= tick_interval:
                    last_tick = time.time()
                    on_tick()
                prev, now = now, self.date()
                if now >= target:
                    break
                # 事件弹窗等会把游戏停住：日期一阵子没动就看看是不是暂停了，是就继续
                stalled = stalled + 1 if now == prev else 0
                if stalled >= 20 and self.paused():
                    self.resume()
                    stalled = 0
            else:
                raise TimeoutError(f"{timeout} 秒内没有走到 {target}（停在 {now}）")
        finally:
            self.pause()
        return self.date()


# ---------------------------------------------------------------- 存档

def autosaves() -> list[str]:
    return sorted(glob.glob(os.path.join(paths.save_dir(), "autosave*.v3")), key=os.path.getmtime)


def wait_new_save(since: float, timeout: float = 120) -> str:
    """等存档目录里出现修改时间晚于 since 的 .v3，且写完（大小稳定）。返回路径。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        fresh = [p for p in glob.glob(os.path.join(paths.save_dir(), "*.v3")) if os.path.getmtime(p) > since]
        if fresh:
            p = max(fresh, key=os.path.getmtime)
            size = -1
            while size != os.path.getsize(p):   # 文本存档 100MB，写盘要几秒
                size = os.path.getsize(p)
                time.sleep(1.5)
            return p
        time.sleep(1)
    raise TimeoutError(f"{timeout} 秒内没有新存档")
