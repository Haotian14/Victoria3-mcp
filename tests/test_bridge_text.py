from agent.bridge import number, plain
from agent.game import Date


def test_plain_strips_tooltip_markup():
    raw = "\x15tooltippable_name \x15tooltip:dw_1,AHVG0g==,DATA_LAW_TYPE_NAME_TOOLTIP,LawTypeTooltip 农奴制\x15!\x15!"
    assert plain(raw) == "农奴制"
    assert plain("大清") == "大清"


def test_number():
    assert number("108499851.86") == 108499851.86
    assert number("+82%") == 82.0
    assert number("-1,234.5") == -1234.5
    assert number("12K") == 12000.0
    assert number("轧棉机") is None


def test_date_parse():
    assert Date.parse("1836.3.1") == Date(1836, 3, 1)
    assert Date.parse("3月 10, 1836") == Date(1836, 3, 10)
    assert Date.parse("March 10, 1836") == Date(1836, 3, 10)
    assert Date(1836, 12, 5).next_month() == Date(1837, 1, 1)
    assert Date(1837, 2, 1).months_since(Date(1836, 1, 1)) == 13
    assert Date(1836, 3, 1) > Date(1836, 2, 28)
