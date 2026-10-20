"""动作层的逻辑（不连游戏）：用假桥接层模拟「执行后下一次读数变化」。"""

import pytest

from agent import actions
from agent.actions import Actions, _diff, _event_window


class FakeBridge:
    """read：按表达式返回值；exec 记录语句并调用 on_exec 改状态。"""

    def __init__(self, values: dict[str, str]):
        self.values = values
        self.executed: list[str] = []
        self.on_exec = lambda stmt: None

    def read(self, text, path=None):
        key = text[1:-1] if text.startswith("[") and text.endswith("]") else text
        return self.values.get(key, "")

    def read_many(self, exprs, path=None):
        return [self.values.get(e, "") for e in exprs]

    def exec(self, stmt, path=None):
        self.executed.append(stmt)
        self.on_exec(stmt)


def test_set_level_reads_current_from_the_only_invalid_button():
    p = actions.PLAYER
    b = FakeBridge({f"IsValid({p}.SetMilitaryWageLevel{t})": "0" if t == "Medium" else "1" for t in actions.LEVELS})

    def switch(stmt):
        for t in actions.LEVELS:
            b.values[f"IsValid({p}.SetMilitaryWageLevel{t})"] = "0" if t == "High" else "1"

    b.on_exec = switch
    r = Actions(b).set_wage("Military", "High")
    assert r.ok and (r.before, r.after) == ("Medium", "High")
    assert b.executed == [f"Execute({p}.SetMilitaryWageLevelHigh)"]


def test_set_level_rejects_unknown_level():
    with pytest.raises(ValueError):
        Actions(FakeBridge({})).set_wage("Military", "Huge")
    with pytest.raises(ValueError):
        Actions(FakeBridge({})).set_wage("Navy", "High")


def test_command_without_target_waits_for_any_change():
    b = FakeBridge({"IsValid(X.Toggle)": "1", "X.IsOn": "0"})
    b.on_exec = lambda stmt: b.values.update({"X.IsOn": "1"})
    r = Actions(b).command("X.Toggle", "X.IsOn")
    assert r.ok and (r.before, r.after) == ("0", "1")


def test_command_reports_game_reason_when_invalid():
    b = FakeBridge({"IsValid(X.Toggle)": "0", "GetDesc(X.Toggle)": "建造已经在进行中。", "X.IsOn": "0"})
    r = Actions(b).command("X.Toggle", "X.IsOn")
    assert not r.ok and "建造已经在进行中" in r.detail
    assert b.executed == []


def test_command_with_target_already_reached_does_nothing():
    b = FakeBridge({"X.Level": "High"})
    r = Actions(b).command("X.SetHigh", "X.Level", target="High")
    assert r.ok and r.detail == "已是目标状态" and b.executed == []


def test_country_command_whitelist():
    with pytest.raises(ValueError):
        Actions(FakeBridge({})).country_command("Annex")


def test_event_window_spec_points_handle_and_option_array():
    assert _event_window(33554433) == "0:88:q=b1;0:110:a=0;1:10:i=33554433"


def test_diplo_window_copies_countries_and_type_from_action():
    spec = actions._diplo_window(1)
    assert "0:d8:i=c1@10" in spec and "0:dc:i=c1@14" in spec and "0:f0:q=c1@28" in spec
    assert "0:e0:i=-1" in spec and "0:e4:i=-1" in spec


def test_proposal_kind_takes_first_valid_part():
    assert actions._proposal_kind(["1", "", "0", "1"]) == "treaty"
    assert actions._proposal_kind(["0", "increase_relations", "0", "0"]) == "action"
    assert actions._proposal_kind(["\x01err", "\x01err", "1", "1"]) == "demand"
    assert actions._proposal_kind(["0", "", "0", "1"]) == "sway"
    assert actions._proposal_kind(["0", "", "0", "0"]) == "?"


def test_diff_keeps_changed_fields_only():
    a = {"modifiers": ["x"], "GetPrestige": "10"}
    b = {"modifiers": ["x", "y"], "GetPrestige": "10"}
    assert _diff(b, a) == {"modifiers": ["x", "y"]}
    assert _diff(a, a) == {}


def test_answered_event_is_not_answered_again(monkeypatch):
    monkeypatch.setitem(actions._ANSWERED, 7, 1)
    b = FakeBridge({})
    r = Actions(b).choose_event_option(7, 0)
    assert not r.ok and "已经选过" in r.detail
    assert b.executed == []
