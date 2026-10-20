from agent import pdx


def obj(text):
    return pdx.to_obj(pdx.parse(text))


def test_basic_types():
    d = obj('a = 1  b = -2.5  c = yes  d = no  e = "x y"  f = 1836.1.1  g = word')
    assert d == {"a": 1, "b": -2.5, "c": True, "d": False, "e": "x y", "f": "1836.1.1", "g": "word"}


def test_nested_and_value_lists():
    d = obj("pm = { techs = { a b } mods = { x = 1 } }")
    assert d == {"pm": {"techs": ["a", "b"], "mods": {"x": 1}}}


def test_repeated_keys_merge():
    d = obj("k = 1 k = 2 k = 3 single = { v = 1 }")
    assert d["k"] == [1, 2, 3]
    assert d["single"] == {"v": 1}


def test_list_value_not_confused_with_repeats():
    # 只出现一次、值本身就是列表，不应被当成「重复键」
    d = obj("techs = { a b }")
    assert d == {"techs": ["a", "b"]}


def test_comparison_and_comments():
    d = obj("trigger = { gdp > 100  # 注释\n rank <= 3 }")
    assert d["trigger"] == {"gdp": {"op": ">", "value": 100}, "rank": {"op": "<=", "value": 3}}


def test_typed_values_and_math():
    d = obj("color = rgb { 1 2 3 }  v = @[ a * 2 ]  @x = 5")
    assert d["color"] == {"_type": "rgb", "_values": [1, 2, 3]}
    assert d["v"] == "@[ a * 2 ]"
    assert d["@x"] == 5


def test_anonymous_blocks():
    d = obj("arr = { { a = 1 } { a = 2 } }")
    assert d == {"arr": [{"a": 1}, {"a": 2}]}


def test_bom_and_unclosed_block_tolerated():
    d = obj("﻿a = { b = 1 ")
    assert d == {"a": {"b": 1}}


def test_stray_closing_brace_tolerated():
    assert obj("a = 1 } b = 2") == {"a": 1, "b": 2}


def test_quoted_escape():
    assert obj(r'a = "say \"hi\""') == {"a": 'say "hi"'}


def test_block_as_key():
    # 存档的移民目标以块为键
    obj = pdx.to_obj(pdx.parse("m={ { culture=49 type=migration } = { num=432 } }"))
    pair = obj["m"][0]
    assert pair["_type"] == "_pair"
    key, value = pair["_values"]
    assert key == {"culture": 49, "type": "migration"} and value == {"num": 432}
