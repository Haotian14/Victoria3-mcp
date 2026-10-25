"""真实征召入口的数量和动员状态后验，布局不匹配时不得点击。"""
import pytest

from agent.bridge import GameError
from agent.coverage import Coverage


class ConscriptBridge:
    def __init__(self, index=33):
        self.index, self.count, self.clicked, self.closed = index, 0, 0, False

    def read(self, expr, path=None):
        if "CanRecruitConscriptUnit" in expr:
            return "1"
        if "GetMaxConscripts" in expr:
            return str(self.count)
        if "HasRaisedConscripts" in expr:
            return "0"
        if "GetNameNoFormatting" in expr:
            return "军团"
        raise AssertionError(expr)

    def exec(self, stmt, path=None):
        if stmt == "MapListOption.OnClick":
            self.count += 1
            self.clicked += 1
        elif stmt == "MapListPanelManager.CloseCurrentPanel":
            self.closed = True
        else:
            assert stmt == "MilitaryFormation.OnClickRecruitConscript(CombatUnitType.Self)"

    def eval_raw(self, stmt):
        return bytes(8) + (1000).to_bytes(8, 'little') + bytes(48)

    def mem_read(self, addr, size):
        if addr == 1000:
            data = bytearray(32)
            data[0:8] = (2000).to_bytes(8, 'little')
            data[12:16] = (43).to_bytes(4, 'little')
            data[24:28] = self.index.to_bytes(4, 'little')
            return bytes(data)
        assert addr == 2000 + self.index * 8
        return (3000).to_bytes(8, 'little')

    def rows(self, stmt, fields, path=None):
        return [["1", str(self.count), "25", "军团"]]


def test_recruit_conscripts_verifies_each_unit_and_leaves_unmobilized():
    bridge = ConscriptBridge()
    result = Coverage(bridge).recruit_conscripts(0, 'combat_unit_type_irregular_infantry', 10)
    assert result.ok and result.before == 0 and result.after == 10
    assert bridge.clicked == 10 and bridge.closed


def test_conscript_panel_layout_mismatch_never_clicks():
    bridge = ConscriptBridge(index=32)
    with pytest.raises(GameError, match='面板布局不匹配'):
        Coverage(bridge).recruit_conscripts(0, 'combat_unit_type_irregular_infantry', 10)
    assert bridge.clicked == 0 and bridge.closed
