"""把同一run逐年记录与UP原帧的最近日期对齐；不插值、不混不同战役。"""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import re

from yearly_compare import _load, _pick, _yearly


def day(value: str) -> date:
    return date(*map(int, re.split(r'[.-]', value)))


def amount(value: str) -> float | None:
    match = re.search(r'([+-]?[\d,.]+)\s*([KMB]?)', value)
    if not match:
        return None
    return float(match[1].replace(',', '')) * {'': 1, 'K': 1e3, 'M': 1e6, 'B': 1e9}[match[2]]


def read_up(path: Path) -> list[dict]:
    """只读宝宝主档，保留日期/置信/帧名；不从旧v6或进阶档补值。"""
    body = path.read_text(encoding='utf-8').split('## 1. 宝宝巴士主档', 1)[1].split('## 2.', 1)[0]
    rows = []
    for line in body.splitlines():
        columns = [x.strip() for x in line.strip().strip('|').split('|')]
        if len(columns) != 12 or not re.fullmatch(r'18\d\d', columns[0]):
            continue
        year, dt, construction, gdp, literacy, sol, population, cash, balance, events, evidence, confidence = columns
        match = re.fullmatch(r'([\d,]+)/([\d,]+)', construction)
        rows.append(dict(year=int(year), date=dt,
                         construction_used=float(match[1].replace(',', '')) if match else None,
                         construction=float(match[2].replace(',', '')) if match else None,
                         gdp=amount(gdp), literacy=amount(literacy) / 100, sol=amount(sol),
                         population=amount(population), money=amount(cash) if not cash.startswith('?') else None,
                         balance=amount(balance.replace('**', '')), events=events, evidence=evidence,
                         confidence=confidence))
    if len(rows) != 30:
        raise ValueError(f'宝宝主档应为30行，实际{len(rows)}；未继续生成对比')
    return rows


def align(run: dict, up: list[dict]) -> list[dict]:
    fiscal = run.get('fiscal_history') or run['history']
    start, end = day(run['start']), day(run['end'])
    output = []
    for anchor in up:
        target = day(anchor['date'])
        if not start <= target <= end:
            continue
        closest = min(fiscal, key=lambda r: (abs((day(r['date']) - target).days), day(r['date'])))
        preceding = [r for r in run['history'] if day(r['date']) <= day(closest['date'])]
        state = preceding[-1] if preceding else None
        output.append(dict(up=anchor, ours=closest,
                           date_difference_days=(day(closest['date']) - target).days,
                           monthly_state=state))
    return output


def effective_laws(run: dict) -> dict[str, dict]:
    """界面列表可显示制定中的目标法。推进标记存在时保留该组此前生效法。

    仅供报告重建，不改原始记录或策略输入；最终状态需与GetActiveGroupLaw只读探针核对。
    """
    previous, output = {}, {}
    monthly = [r for r in run.get('fiscal_history', []) if r.get('cadence') == 'monthly']
    for row in sorted(monthly, key=lambda r: day(r['date'])):
        actual = dict(row.get('law_keys') or {})
        for group, key in actual.items():
            if key == row.get('enacting') and group in previous:
                actual[group] = previous[group]
        previous = actual
        output[row['date']] = actual
    endpoint = run.get('verified_endpoint') or {}
    if endpoint.get('actual_laws'):
        output[endpoint['date']] = endpoint['actual_laws']
    return output


def attach_endpoint(run: dict, endpoint: dict) -> dict:
    """仅在报告副本中补齐同日终点的建筑存量，保留runs.jsonl原始记录。"""
    if endpoint.get('label') != run['label'] or endpoint.get('date') != run['end']:
        raise ValueError('终点探针的label/日期与本run不符')
    history = [dict(row, **endpoint['metrics']) if row['date'] == run['end'] else row
               for row in run['history']]
    return dict(run, history=history, verified_endpoint=endpoint)


def fmt(value, unit=1, digits=1):
    return '?' if value is None else f'{value / unit:,.{digits}f}'


def build(row):
    return f"{fmt(row.get('construction_used'), digits=0)}/{fmt(row.get('construction'), digits=0)}"


def render(run: dict, aligned: list[dict]) -> str:
    laws_by_date = effective_laws(run)
    lines = [f"# 与UP主档的近日期对比：{run['label']}", '',
             f"运行：{run['start']}→{run['end']}（{run['months']}个月）。UP取docs/up_yearly.md宝宝主档；我方取本run最近周/月样本。",
             '每行保留双方实际日期，不插值；GDP/人口单位M，国库M，周结余K。UP国库未知不填0；1840原帧置信B，只作参考。', '',
             '| 年份 | UP日期 / 我方日期（差天） | UP已用/基础 | 我方已用/基础 | UP / 我方GDP | GDP差 | UP / 我方SoL | UP / 我方识字率 | UP / 我方国库 | UP / 我方周结余 |',
             '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for a in aligned:
        u, o = a['up'], a['ours']
        delta = (o['gdp'] / u['gdp'] - 1) * 100
        lines.append(f"| {u['year']} | {u['date']} / {o['date']}（{a['date_difference_days']:+}） | "
                     f"{build(u)} | {build(o)} | {fmt(u['gdp'], 1e6)} / {fmt(o['gdp'], 1e6)} | {delta:+.1f}% | "
                     f"{fmt(u['sol'])} / {fmt(o['sol'], digits=2)} | {fmt(u['literacy'], .01)}% / {fmt(o['literacy'], .01)}% | "
                     f"{fmt(u['money'], 1e6)} / {fmt(o['money'], 1e6)} | "
                     f"{fmt(u['balance'], 1e3)} / {fmt(o['balance'], 1e3)} |")
    lines += ['', '> 仅比较运行起止之间的UP原帧；若终点为1846.1，不与UP1846.11的年末帧直接比较。', '',
              '## 人口与人均产出', '',
              '同一近日期样本；人口单位M，人均GDP直接使用GDP/人口，双方统一单位。UP人口原帧取整，差值也受其精度影响。', '',
              '| 年份 | UP / 我方人口 | UP / 我方人均GDP | 人均GDP差 |',
              '|---|---:|---:|---:|']
    for a in aligned:
        u, o = a['up'], a['ours']
        up_per, our_per = u['gdp'] / u['population'], o['gdp'] / o['population']
        lines.append(f"| {u['year']} | {fmt(u['population'], 1e6)} / {fmt(o['population'], 1e6)} | "
                     f"{fmt(up_per, digits=3)} / {fmt(our_per, digits=3)} | {(our_per / up_per - 1) * 100:+.1f}% |")
    lines += ['',
              '## 我方每年制度与建设存量', '',
              '| 年份 | 状态日期 | 贸易法 | 土地法 | 经济法 | 教育法 | 建造部门级数 | 大学 | 贸易中心 | 纺织厂 |',
              '|---|---|---|---|---|---|---:|---:|---:|---:|']
    for year, (_, _, row) in sorted(_yearly(run['history']).items()):
        candidates = [d for d in laws_by_date if day(d) <= day(row['date'])]
        laws = laws_by_date[candidates[-1]] if candidates else row.get('law_keys') or {}
        levels = row.get('building_levels') or {}
        l = lambda k: laws.get('lawgroup_' + k, '?')
        n = lambda k: str(levels.get('building_' + k, 0)) if levels else '?'
        lines.append(f"| {year} | {row['date']} | {l('trade_policy')} | {l('land_reform')} | "
                     f"{l('economic_system')} | {l('education_system')} | {n('construction_sector')} | "
                     f"{n('university')} | {n('trade_center')} | {n('textile_mill')} |")
    lines += ['', '法律按月度显示法与正在制定标记重建生效法：正在制定的目标不能算已通过，保持该组此前确认生效法。通过日期只有月间精度；最终结果另与GetActiveGroupLaw探针核对。原始law_keys字段不回写。', '',
              '## 原帧与选样依据', '']
    for a in aligned:
        u = a['up']
        lines.append(f"- {u['year']}：{u['evidence']}；置信{u['confidence']}；{u['events']}")
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--data-out', required=True)
    parser.add_argument('--endpoint', help='可选：本run同日只读终点探针，补齐终点存量/核验法律')
    args = parser.parse_args()
    run = _pick(_load(Path('logs/runs.jsonl')), args.label)
    if args.endpoint:
        run = attach_endpoint(run, json.loads(Path(args.endpoint).read_text(encoding='utf-8')))
    aligned = align(run, read_up(Path('docs/up_yearly.md')))
    Path(args.out).write_text(render(run, aligned), encoding='utf-8')
    Path(args.data_out).write_text(json.dumps(dict(label=args.label, start=run['start'], end=run['end'],
                                                  effective_laws_by_month=effective_laws(run),
                                                  endpoint_source=args.endpoint,
                                                  comparisons=aligned), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'wrote {args.out}; {len(aligned)} aligned years')


if __name__ == '__main__':
    main()
