"""按 1.13.11 文本存档的真实结构构造的最小 gamestate（数值是编的）。"""

from agent import pdx, state
from agent.gamedata import GameData

SAVE = """
date=1836.1.1
meta_data={ name="大清" }
player_manager={ database={ 0={ user="someone" country=156 } } }
country_manager={ database={
    156={ definition=CHI government=gov_absolute_empire tax_level=low states={ 23 24 }
          budget={ money=1000.5 credit=20000 base_wage=400 weekly_income={ 0 100 50 }
                   weekly_expenses={ 0 30 }
                   current_price_report={ goods={ 0={ value=10.5 } 1={ value=35 } } } } }
    7={ definition=GBR states={ 99 } }
} }
market_manager={ world_market={ price_trend={ channels={
    0={ date=1836.1.1 index=1 values={ 18 19 } } 1={ values={ 31 } } } } } }
technology={ database={ 72={ country=156 acquired_technologies={ enclosure manufacturies } }
                        73={ country=7 acquired_technologies={ railways } } } }
laws={ database={ 1={ law=law_serfdom country=156 active=yes }
                  2={ law=law_chiefdom country=156 }
                  3={ law=law_monarchy country=7 active=yes } } }
states={ database={ 23={ region=STATE_SHANDONG arable_land=350 infrastructure=91 }
                    24={ region=STATE_JIANGSU arable_land=200 }
                    99={ region=STATE_HOME_COUNTIES } } }
building_manager={ database={
    1={ building=building_wheat_farm state=23 levels=2 staffing=1 profit_after_reserves=100.5
        production_methods={ pm_simple_farming pm_no_secondary } }
    2={ building=building_textile_mill state=24 levels=8 staffing=8 }
    3={ building=building_railway state=99 levels=5 }
} }
"""


def make_gd():
    gd = GameData.__new__(GameData)
    gd.goods = {"grain": {"cost": 20, "index": 0}, "clothes": {"cost": 30, "index": 1}}
    return gd


def extract():
    return state.extract(pdx.to_obj(pdx.parse(SAVE)), make_gd())


def test_player_and_country():
    cs = extract()
    assert (cs.country_id, cs.tag, cs.name) == (156, "CHI", "大清")
    assert cs.government == "gov_absolute_empire" and cs.tax_level == "low"
    assert cs.money == 1000.5 and cs.credit == 20000
    assert cs.weekly_income == 150 and cs.weekly_expense == 30


def test_prices_mapped_by_goods_index():
    cs = extract()
    assert cs.prices == {"grain": 10.5, "clothes": 35.0}
    assert cs.world_prices == {"grain": 19.0, "clothes": 31.0}  # 取趋势里最新的值


def test_only_own_techs_and_active_laws():
    cs = extract()
    assert cs.techs == {"enclosure", "manufacturies"}
    assert cs.laws == {"law_serfdom"}


def test_buildings_grouped_by_own_states():
    cs = extract()
    assert [s.region for s in cs.states] == ["STATE_SHANDONG", "STATE_JIANGSU"]
    blds = {b.building: b for b in cs.buildings()}
    assert set(blds) == {"building_wheat_farm", "building_textile_mill"}
    assert blds["building_wheat_farm"].pms == ["pm_simple_farming", "pm_no_secondary"]
    assert blds["building_wheat_farm"].profit == 100.5
    assert blds["building_textile_mill"].profit is None


def test_other_country_by_id():
    cs = state.extract(pdx.to_obj(pdx.parse(SAVE)), make_gd(), country_id=7)
    assert cs.tag == "GBR" and cs.name is None
    assert cs.laws == {"law_monarchy"} and cs.techs == {"railways"}
