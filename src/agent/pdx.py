"""Paradox 脚本格式（Jomini 文本）解析：游戏 common/ 下的定义文件与文本存档同一套语法。

    key = value          key = { ... }         key > 3          { a b c }
    color = rgb { 1 2 3 }                      @var = 5         value = @[ a * 2 ]

parse() 返回有序条目列表 [(key, op, value)]，同名键可重复出现（存档里很常见）；
值是标量字符串或嵌套条目列表。to_obj() 再把它压成 JSON 友好的 dict / list：
重复键合并成列表，纯值块（`{ a b c }`）变成列表，yes/no 与数字转成对应类型。
"""

from __future__ import annotations

import re
from typing import Any, Iterator

Entry = tuple[str | None, str | None, Any]

# 顺序有讲究：先匹配多字符运算符；`@[ ... ]` 内联算式整体当一个标量
_TOKEN = re.compile(r"""
    (?P<ws>\s+|\#[^\n]*)
  | (?P<str>"(?:[^"\\]|\\.)*")
  | (?P<math>@\[[^\]]*\])
  | (?P<op><=|>=|!=|\?=|==|=|<|>)
  | (?P<lb>\{)
  | (?P<rb>\})
  | (?P<word>[^\s=<>!?{}"\#]+)
""", re.VERBOSE)

_INT = re.compile(r"-?\d+$")
_FLOAT = re.compile(r"-?(?:\d+\.\d*|\.\d+)$")


class ParseError(ValueError):
    pass


def tokenize(text: str) -> Iterator[tuple[str, str]]:
    pos, n = 0, len(text)
    if text.startswith("﻿"):
        pos = 1
    while pos < n:
        m = _TOKEN.match(text, pos)
        if not m:
            raise ParseError(f"无法识别的字符 {text[pos]!r}（偏移 {pos}）")
        pos = m.end()
        kind = m.lastgroup
        if kind != "ws":
            yield kind, m.group()


def parse(text: str) -> list[Entry]:
    tokens = list(tokenize(text))
    entries, _ = _block(tokens, 0, top=True)
    return entries


def _block(tokens: list[tuple[str, str]], i: int, top: bool = False) -> tuple[list[Entry], int]:
    out: list[Entry] = []
    n = len(tokens)
    while i < n:
        kind, tok = tokens[i]
        if kind == "rb":
            if top:
                # 游戏文件里偶有多余的右括号，游戏本身会忽略，这里也忽略
                i += 1
                continue
            return out, i + 1
        if kind == "lb":
            # 匿名块：存档里的 `{ { ... } { ... } }` 数组
            sub, i = _block(tokens, i + 1)
            out.append((None, None, sub))
            continue
        if kind == "op":
            raise ParseError(f"运算符 {tok} 前缺少键（第 {i} 个记号）")
        if i + 1 < n and tokens[i + 1][0] == "op":
            op = tokens[i + 1][1]
            value, i = _value(tokens, i + 2)
            out.append((_scalar_text(kind, tok), op, value))
        elif i + 1 < n and tokens[i + 1][0] == "lb" and kind == "word" and not top:
            # 列表里的带类型块，如 `{ rgb { 1 2 3 } }` —— 少见，按值处理
            sub, i = _block(tokens, i + 2)
            out.append((None, None, {"_type": tok, "_values": sub}))
        else:
            out.append((None, None, _scalar_text(kind, tok)))
            i += 1
    # 未闭合的块到文件尾自动闭合：游戏自带文件里就有少一个 } 的（dna_data/），游戏照样加载
    return out, i


def _value(tokens: list[tuple[str, str]], i: int) -> tuple[Any, int]:
    if i >= len(tokens):
        raise ParseError("= 后缺少值")
    kind, tok = tokens[i]
    if kind == "lb":
        return _block(tokens, i + 1)
    if kind in ("rb", "op"):
        raise ParseError(f"= 后出现 {tok}")
    # `rgb { ... }` / `hsv { ... }` 这类带类型的值
    if kind == "word" and i + 1 < len(tokens) and tokens[i + 1][0] == "lb":
        sub, j = _block(tokens, i + 2)
        return {"_type": tok, "_values": sub}, j
    return _scalar_text(kind, tok), i + 1


def _scalar_text(kind: str, tok: str) -> str:
    if kind == "str":
        return tok[1:-1].replace('\\"', '"')
    return tok


# ---------------------------------------------------------------- 转 JSON


def scalar(s: str) -> Any:
    if s == "yes":
        return True
    if s == "no":
        return False
    if _INT.match(s):
        return int(s)
    if _FLOAT.match(s):
        return float(s)
    return s


class _Multi(list):
    """区分「重复键合并出来的列表」与「值本身就是列表」。"""


def to_obj(value: Any) -> Any:
    """条目列表 → dict / list。比较运算（`>`、`<` 等）保留成 {"op": ..., "value": ...}。"""
    if isinstance(value, str):
        return scalar(value)
    if isinstance(value, dict):  # 带类型的值
        return {"_type": value["_type"], "_values": to_obj(value["_values"])}
    keyed = [e for e in value if e[0] is not None]
    loose = [e for e in value if e[0] is None]
    if not keyed:
        return [to_obj(v) for _, _, v in loose]
    out: dict[str, Any] = {}
    for k, op, v in keyed:
        item = to_obj(v)
        if op not in ("=", "?=", "=="):
            item = {"op": op, "value": item}
        if k in out:
            prev = out[k]
            if isinstance(prev, _Multi):
                prev.append(item)
            else:
                out[k] = _Multi([prev, item])
        else:
            out[k] = item
    if loose:
        out["_values"] = [to_obj(v) for _, _, v in loose]
    return {k: (list(v) if isinstance(v, _Multi) else v) for k, v in out.items()}


def as_list(v: Any) -> list:
    """重复键合并后可能是单个值也可能是列表，统一成列表。"""
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def load_file(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8-sig") as f:
        return to_obj(parse(f.read()))
