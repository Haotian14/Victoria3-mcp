"""经济账用构造的最小数据测，不依赖 data/ 里抽出来的真实定义。"""

from agent.gamedata import GameData
from agent.strategy import economy


def make_gd():
    gd = GameData.__new__(GameData)
    gd.goods = {"grain": {"cost": 20}, "groceries": {"cost": 30}, "sugar": {"cost": 30}}
    gd.techs = {"distillation": {"requires": ["basics"]}, "basics": {"requires": []}}
    gd.pms = {
        "pm_bakery": {"techs": [], "unlocking_laws": [], "disallowing_laws": [],
                      "inputs": {"grain": 40}, "outputs": {"groceries": 45},
                      "employment": {"laborers": 4500, "shopkeepers": 500}},
        "pm_sweeteners": {"techs": ["distillation"], "unlocking_laws": [], "disallowing_laws": [],
                          "inputs": {"grain": 40, "sugar": 15}, "outputs": {"groceries": 65},
                          "employment": {"laborers": 4000, "shopkeepers": 500, "machinists": 500}},
        "pm_slaves": {"techs": [], "unlocking_laws": ["law_slavery"], "disallowing_laws": [],
                      "inputs": {}, "outputs": {"groceries": 100}, "employment": {}},
    }
    gd.pmgs = {"pmg_base": {"pms": ["pm_bakery", "pm_sweeteners"]},
               "pmg_extra": {"pms": ["pm_slaves"]}}
    gd.buildings = {"building_food": {"pmgs": ["pmg_base", "pmg_extra"], "construction": 600,
                                      "buildable": True, "techs": []}}
    return gd


def test_base_pm_without_techs():
    gd = make_gd()
    e = economy.building_economics(gd, "building_food", techs=set(), laws=set())
    assert [c.pm for c in e.choices] == ["pm_bakery"]
    assert e.value_added == 45 * 30 - 40 * 20  # 550，与游戏文件注释里的 profit 一致
    assert e.workers == 5000


def test_better_pm_once_unlocked():
    gd = make_gd()
    e = economy.building_economics(gd, "building_food", techs={"distillation"}, laws=set())
    assert e.choices[0].pm == "pm_sweeteners"
    assert e.value_added == 65 * 30 - 40 * 20 - 15 * 30  # 700


def test_law_gated_pm():
    gd = make_gd()
    without = economy.building_economics(gd, "building_food", techs=set(), laws=set())
    with_law = economy.building_economics(gd, "building_food", techs=set(), laws={"law_slavery"})
    assert len(without.choices) == 1
    assert with_law.value_added == without.value_added + 3000


def test_market_prices_change_choice():
    gd = make_gd()
    # 糖价暴涨时，即使已解锁也不该用甜味剂
    prices = {"grain": 20, "groceries": 30, "sugar": 100}
    e = economy.building_economics(gd, "building_food", prices, techs={"distillation"}, laws=set())
    assert e.choices[0].pm == "pm_bakery"


def test_tech_closure_adds_prereqs():
    gd = make_gd()
    assert gd.tech_closure({"distillation"}) == {"distillation", "basics"}


def test_rank_per_construction():
    gd = make_gd()
    rows = economy.rank_buildings(gd, techs=set(), laws=set())
    assert rows[0].building == "building_food"
    assert rows[0].per_construction == 550 / 600
