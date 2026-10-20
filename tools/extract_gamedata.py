"""从游戏本体抽取静态数据 → src/agent/data/*.json

数据来源全在本机游戏目录里（不改动其中任何文件）：

1. game/common/ 下的脚本定义 —— 商品基准价、建筑与生产方式（投入 / 产出 / 雇佣）、
   生产方式组、科技与前置、法律与法律组、建造点数；
2. game/localization/{simp_chinese,english}/ —— 中英文名。

生产方式里的数字是「每级建筑、满员时」的值（workforce_scaled 按雇佣比例缩放，
level_scaled 按等级缩放），实际产出还要乘吞吐量修正，那是运行时的事。

用法：
    python tools/extract_gamedata.py            # 游戏目录自动找，或设 V3MCP_GAME_DIR
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys
from typing import Any

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT = os.path.join(ROOT, "src", "agent", "data")
sys.path.insert(0, os.path.join(ROOT, "src"))

from agent import paths, pdx  # noqa: E402

LANGS = {"zh": "simp_chinese", "en": "english"}

_GOODS_IN = re.compile(r"goods_input_(\w+)_add$")
_GOODS_OUT = re.compile(r"goods_output_(\w+)_add$")
_EMPLOY = re.compile(r"building_employment_(\w+)_add$")


def load_dir(sub: str) -> dict[str, Any]:
    """读 common/<sub>/ 下全部 .txt，合并成一个 dict（后读的同名定义覆盖先读的，与游戏一致）。"""
    out: dict[str, Any] = {}
    for p in sorted(glob.glob(os.path.join(paths.common_dir(), sub, "**", "*.txt"), recursive=True)):
        data = pdx.load_file(p)
        if isinstance(data, dict):
            out.update({k: v for k, v in data.items() if not k.startswith("@") and k != "_values"})
    return out


# ---------------------------------------------------------------- 本地化

_LOC_LINE = re.compile(r'^\s+([\w.\-]+):\d*\s+"(.*)"\s*(?:#.*)?$')
_LOC_REF = re.compile(r"^\$([\w.\-]+)\$$")


def load_localization(lang: str) -> dict[str, str]:
    table: dict[str, str] = {}
    for p in glob.glob(os.path.join(paths.localization_dir(lang), "**", "*.yml"), recursive=True):
        with open(p, encoding="utf-8-sig", errors="replace") as f:
            for line in f:
                m = _LOC_LINE.match(line)
                if m:
                    table[m.group(1)] = m.group(2)
    # 整条只是另一条的引用（`"$building_dummy$"`）时展开一层
    for k, v in table.items():
        m = _LOC_REF.match(v)
        if m and m.group(1) in table:
            table[k] = table[m.group(1)]
    return table


class Names:
    def __init__(self) -> None:
        self.tables = {short: load_localization(lang) for short, lang in LANGS.items()}

    def __call__(self, key: str) -> dict[str, str]:
        return {short: t.get(key, key) for short, t in self.tables.items()}


# ---------------------------------------------------------------- 各类定义


def extract_goods(names: Names) -> dict[str, Any]:
    return {
        k: {"name": names(k), "cost": v.get("cost"), "category": v.get("category")}
        for k, v in load_dir("goods").items()
    }


def extract_production_methods(names: Names) -> dict[str, Any]:
    out = {}
    for k, v in load_dir("production_methods").items():
        mods = v.get("building_modifiers") or {}
        inputs: dict[str, float] = {}
        outputs: dict[str, float] = {}
        employment: dict[str, float] = {}
        for scope in ("workforce_scaled", "level_scaled", "unscaled"):
            for key, val in (mods.get(scope) or {}).items():
                if not isinstance(val, (int, float)):
                    continue
                if m := _GOODS_IN.match(key):
                    inputs[m.group(1)] = inputs.get(m.group(1), 0) + val
                elif m := _GOODS_OUT.match(key):
                    outputs[m.group(1)] = outputs.get(m.group(1), 0) + val
                elif m := _EMPLOY.match(key):
                    employment[m.group(1)] = employment.get(m.group(1), 0) + val
        out[k] = {
            "name": names(k),
            "techs": pdx.as_list(v.get("unlocking_technologies")),
            "unlocking_laws": pdx.as_list(v.get("unlocking_laws")),
            "disallowing_laws": pdx.as_list(v.get("disallowing_laws")),
            "inputs": inputs,
            "outputs": outputs,
            "employment": employment,
        }
    return out


def extract_pm_groups(names: Names) -> dict[str, Any]:
    return {
        k: {"name": names(k), "pms": pdx.as_list(v.get("production_methods"))}
        for k, v in load_dir("production_method_groups").items()
    }


def extract_buildings(names: Names, script_values: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in load_dir("buildings").items():
        cost = v.get("required_construction")
        if isinstance(cost, str):
            cost = script_values.get(cost)
        out[k] = {
            "name": names(k),
            "group": v.get("building_group"),
            "techs": pdx.as_list(v.get("unlocking_technologies")),
            "pmgs": pdx.as_list(v.get("production_method_groups")),
            "construction": cost if isinstance(cost, (int, float)) else None,
            "buildable": v.get("buildable", True),
            "expandable": v.get("expandable", True),
        }
    return out


def extract_technologies(names: Names) -> dict[str, Any]:
    out = {}
    for k, v in load_dir(os.path.join("technology", "technologies")).items():
        out[k] = {
            "name": names(k),
            "era": v.get("era"),
            "category": v.get("category"),
            "requires": pdx.as_list(v.get("unlocking_technologies")),
            "can_research": v.get("can_research", True),
        }
    return out


def extract_laws(names: Names) -> tuple[dict[str, Any], dict[str, Any]]:
    groups = {
        k: {"name": names(k), "category": v.get("law_group_category")}
        for k, v in load_dir("law_groups").items()
    }
    laws = {
        k: {
            "name": names(k),
            "group": v.get("group"),
            "progressiveness": v.get("progressiveness"),
            "techs": pdx.as_list(v.get("unlocking_technologies")),
            "disallowing_laws": pdx.as_list(v.get("disallowing_laws")),
        }
        for k, v in load_dir("laws").items()
    }
    return laws, groups


def load_script_values() -> dict[str, Any]:
    """只取直接写成数字的 script value（如 construction_cost_high = 600）。"""
    return {k: v for k, v in load_dir("script_values").items() if isinstance(v, (int, float))}


def game_version() -> str | None:
    p = os.path.join(paths.game_dir(), "launcher", "launcher-settings.json")
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f).get("rawVersion")
    except (OSError, ValueError):
        return None


def write(name: str, payload: dict[str, Any]) -> None:
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, f"{name}.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")


def main() -> None:
    names = Names()
    version = game_version()
    laws, law_groups = extract_laws(names)
    tables = {
        "goods": extract_goods(names),
        "buildings": extract_buildings(names, load_script_values()),
        "production_methods": extract_production_methods(names),
        "production_method_groups": extract_pm_groups(names),
        "technologies": extract_technologies(names),
        "laws": laws,
        "law_groups": law_groups,
    }
    for name, table in tables.items():
        write(name, {"game_version": version, name: table})
        print(f"{name:26s} {len(table):5d}")


if __name__ == "__main__":
    main()
