# 玩家操作清单

由 `tools/extract_actions.py` 从游戏界面文件（`game/gui/**/*.gui`）自动生成，机器可读版在
`src/agent/data/actions.json`。每一行是界面按钮背后的一条游戏命令（`Execute(X)`、`AskConfirmation(X)` 等的参数 X），桥接层用同样的 `Execute(X)` 执行。

可达性：**直达** = 从玩家国家沿列表能走到对象，照现有做法即可；**窗口** = 对象只存在于界面窗口 / 弹窗 / 草稿里，要像改组政府那样构造（见 docs/bridge.md）；**组合** = 军事 / 地图类，要组合编队、前线、海域等多个对象；**界面** = 只影响界面显示（改名、开关、定位），不影响局面；**待查** = 接收对象还没归类。

**进度：命令 10 / 265 已验证；按操作种类（只差档位的算一种）6 / 225。**

按可达性（操作种类，已验证 / 总数）：直达 5 / 110，窗口 1 / 31，组合 0 / 77，界面 0 / 7。

不在本表、但同样要打通的：事件选项（事件弹窗，现在由游戏默认选）、立即存档（目前用自动存档）、暂停 / 调速（`TimeKeeper`，已验证，不经 Execute）。

## 国家（5 / 50）

| 状态 | 可达性 | 命令 | 例子 | 界面文件 |
|---|---|---|---|---|
| ✓ `Actions.set_tax` | 直达 | `Country.SetTaxLevelHigh` | `GetPlayer.SetTaxLevelHigh` | budget_panel.gui |
| ✓ `Actions.set_tax` | 直达 | `Country.SetTaxLevelLow` | `GetPlayer.SetTaxLevelLow` | budget_panel.gui |
| ✓ `Actions.set_tax` | 直达 | `Country.SetTaxLevelMedium` | `GetPlayer.SetTaxLevelMedium` | budget_panel.gui |
| ✓ `Actions.set_tax` | 直达 | `Country.SetTaxLevelVeryHigh` | `GetPlayer.SetTaxLevelVeryHigh` | budget_panel.gui |
| ✓ `Actions.set_tax` | 直达 | `Country.SetTaxLevelVeryLow` | `GetPlayer.SetTaxLevelVeryLow` | budget_panel.gui |
|  | 直达 | `Country.ClearDefaultConstructionFleet` | `Country.ClearDefaultConstructionFleet` | right_click_menu.gui |
|  | 直达 | `Country.CreateCompany` | `GetPlayer.CreateCompany(CompanyType.Self)` | companies_panel.gui |
|  | 直达 | `Country.DeclareBankruptcy` | `Country.DeclareBankruptcy` | budget_panel.gui |
|  | 直达 | `Country.DemobilizeAllArmies` | `Country.DemobilizeAllArmies` | panel_military.gui |
|  | 直达 | `Country.Kick` | `Country.GetPowerBloc.Kick(Country.Self)` | right_click_menu.gui |
|  | 直达 | `Country.LeavePowerBloc` | `GetPlayer.LeavePowerBloc` | power_bloc_panel.gui |
|  | 直达 | `Country.MobilizeAllArmies` | `Country.MobilizeAllArmies` | panel_military.gui |
|  | 直达 | `Country.PauseConstruction` | `Country.PauseConstruction` | building_browser_panel.gui, production_methods.gui … |
|  | 直达 | `Country.PauseShipConstruction` | `Country.PauseShipConstruction` | production_methods.gui |
|  | 直达 | `Country.RemoveCompany` | `GetPlayer.RemoveCompany(CompanyType.Self)` | companies_panel.gui, company_panel.gui |
|  | 直达 | `Country.ResumeConstruction` | `Country.ResumeConstruction` | building_browser_panel.gui, production_methods.gui … |
|  | 直达 | `Country.ResumeShipConstruction` | `Country.ResumeShipConstruction` | production_methods.gui |
|  | 直达 | `Country.SetDefaultConstructionFleet` | `Country.SetDefaultConstructionFleet(MilitaryFormation.Self)` | right_click_menu.gui |
|  | 直达 | `Country.SetExportSubventionsHigh` | `GetPlayer.SetExportSubventionsHigh(Goods.Self)` | budget_panel.gui |
|  | 直达 | `Country.SetExportSubventionsLow` | `GetPlayer.SetExportSubventionsLow(Goods.Self)` | budget_panel.gui |
|  | 直达 | `Country.SetExportSubventionsMax` | `GetPlayer.SetExportSubventionsMax(Goods.Self)` | budget_panel.gui |
|  | 直达 | `Country.SetExportTariffsHigh` | `GetPlayer.SetExportTariffsHigh(Goods.Self)` | budget_panel.gui |
|  | 直达 | `Country.SetExportTariffsLow` | `GetPlayer.SetExportTariffsLow(Goods.Self)` | budget_panel.gui |
|  | 直达 | `Country.SetExportTariffsMax` | `GetPlayer.SetExportTariffsMax(Goods.Self)` | budget_panel.gui |
|  | 直达 | `Country.SetExportTariffsNone` | `GetPlayer.SetExportTariffsNone(Goods.Self)` | budget_panel.gui |
|  | 直达 | `Country.SetGovernmentWageLevelHigh` | `GetPlayer.SetGovernmentWageLevelHigh` | budget_panel.gui |
|  | 直达 | `Country.SetGovernmentWageLevelLow` | `GetPlayer.SetGovernmentWageLevelLow` | budget_panel.gui |
|  | 直达 | `Country.SetGovernmentWageLevelMedium` | `GetPlayer.SetGovernmentWageLevelMedium` | budget_panel.gui |
|  | 直达 | `Country.SetGovernmentWageLevelVeryHigh` | `GetPlayer.SetGovernmentWageLevelVeryHigh` | budget_panel.gui |
|  | 直达 | `Country.SetGovernmentWageLevelVeryLow` | `GetPlayer.SetGovernmentWageLevelVeryLow` | budget_panel.gui |
|  | 直达 | `Country.SetImportSubventionsHigh` | `GetPlayer.SetImportSubventionsHigh(Goods.Self)` | budget_panel.gui |
|  | 直达 | `Country.SetImportSubventionsLow` | `GetPlayer.SetImportSubventionsLow(Goods.Self)` | budget_panel.gui |
|  | 直达 | `Country.SetImportSubventionsMax` | `GetPlayer.SetImportSubventionsMax(Goods.Self)` | budget_panel.gui |
|  | 直达 | `Country.SetImportTariffsHigh` | `GetPlayer.SetImportTariffsHigh(Goods.Self)` | budget_panel.gui |
|  | 直达 | `Country.SetImportTariffsLow` | `GetPlayer.SetImportTariffsLow(Goods.Self)` | budget_panel.gui |
|  | 直达 | `Country.SetImportTariffsMax` | `GetPlayer.SetImportTariffsMax(Goods.Self)` | budget_panel.gui |
|  | 直达 | `Country.SetImportTariffsNone` | `GetPlayer.SetImportTariffsNone(Goods.Self)` | budget_panel.gui |
|  | 直达 | `Country.SetMilitaryWageLevelHigh` | `GetPlayer.SetMilitaryWageLevelHigh` | budget_panel.gui |
|  | 直达 | `Country.SetMilitaryWageLevelLow` | `GetPlayer.SetMilitaryWageLevelLow` | budget_panel.gui |
|  | 直达 | `Country.SetMilitaryWageLevelMedium` | `GetPlayer.SetMilitaryWageLevelMedium` | budget_panel.gui |
|  | 直达 | `Country.SetMilitaryWageLevelVeryHigh` | `GetPlayer.SetMilitaryWageLevelVeryHigh` | budget_panel.gui |
|  | 直达 | `Country.SetMilitaryWageLevelVeryLow` | `GetPlayer.SetMilitaryWageLevelVeryLow` | budget_panel.gui |
|  | 直达 | `Country.SetSupplyShipConstructionLevelHigh` | `GetPlayer.SetSupplyShipConstructionLevelHigh` | construction_panel.gui |
|  | 直达 | `Country.SetSupplyShipConstructionLevelLow` | `GetPlayer.SetSupplyShipConstructionLevelLow` | construction_panel.gui |
|  | 直达 | `Country.SetSupplyShipConstructionLevelMedium` | `GetPlayer.SetSupplyShipConstructionLevelMedium` | construction_panel.gui |
|  | 直达 | `Country.SetSupplyShipConstructionLevelVeryHigh` | `GetPlayer.SetSupplyShipConstructionLevelVeryHigh` | construction_panel.gui |
|  | 直达 | `Country.SetSupplyShipConstructionLevelVeryLow` | `GetPlayer.SetSupplyShipConstructionLevelVeryLow` | construction_panel.gui |
|  | 直达 | `Country.StartNegotiationWith` | `AccessPlayer.StartNegotiationWith(InterestGroup.Self)` | right_click_menu.gui |
|  | 界面 | `Country.ToggleIgnoreCountryFormation` | `GetPlayer.ToggleIgnoreCountryFormation(CountryFormation.Self)` | country_formation_panel.gui, culture_panel.gui |
|  | 界面 | `Country.ToggleIgnoreDecision` | `GetPlayer.ToggleIgnoreDecision(Decision.Self)` | journal.gui |

## 经济（2 / 56）

| 状态 | 可达性 | 命令 | 例子 | 界面文件 |
|---|---|---|---|---|
| ✓ `Actions.build` | 直达 | `Building.QueueConstruction` | `Building.QueueConstruction` | build_urban_buildings_menu.gui, building_details_panel.gui … |
| ✓ `Actions.set_pm` | 直达 | `ProductionMethod.GetSwitch` | `ProductionMethod.GetSwitch` | （程序生成的菜单） |
|  | 直达 | `Building.CancelConstruction` | `Building.CancelConstruction` | building_details_panel.gui, goods_local_prices_panel.gui … |
|  | 直达 | `Building.Downsize` | `Building.Downsize` | building_details_panel.gui, goods_state_panel.gui … |
|  | 直达 | `Building.NationalizeBuildingLevels` | `Building.NationalizeBuildingLevels('(int32)1')` | building_details_panel.gui, right_click_menu.gui |
|  | 直达 | `Building.PauseConstructionOutput` | `Building.PauseConstructionOutput` | production_methods.gui |
|  | 直达 | `Building.QueueMilitaryConstruction` | `Building.QueueMilitaryConstruction(MilitaryFormation.Self,CombatUnitType.Self)` | building_details_panel.gui |
|  | 直达 | `Building.ResetProductionMethodsToStandard` | `Building.ResetProductionMethodsToStandard` | right_click_menu.gui |
|  | 直达 | `Building.ResumeConstructionOutput` | `Building.ResumeConstructionOutput` | production_methods.gui |
|  | 直达 | `Building.ToggleAutoExpand` | `Building.ToggleAutoExpand` | building_details_panel.gui |
|  | 直达 | `Building.ToggleAutoExpandOff` | `Building.ToggleAutoExpandOff` | right_click_menu.gui |
|  | 直达 | `Building.ToggleAutoExpandOn` | `Building.ToggleAutoExpandOn` | right_click_menu.gui |
|  | 直达 | `Building.TogglePrivatization` | `Building.TogglePrivatization` | building_details_panel.gui, right_click_menu.gui |
|  | 直达 | `Building.ToggleSubsidies` | `Building.ToggleSubsidies` | building_details_panel.gui, right_click_menu.gui … |
|  | 直达 | `Building.ToggleSubsidiesOff` | `Building.ToggleSubsidiesOff` | right_click_menu.gui |
|  | 直达 | `Building.ToggleSubsidiesOn` | `Building.ToggleSubsidiesOn` | right_click_menu.gui |
|  | 直达 | `BuildingType.ResetProductionMethodsToStandard` | `BuildingType.ResetProductionMethodsToStandard` | right_click_menu.gui |
|  | 直达 | `BuildingType.ToggleMonopoly` | `BuildingType.ToggleMonopoly` | right_click_menu.gui |
|  | 直达 | `Company.ToggleBuildingCharter` | `Company.ToggleBuildingCharter(CompanyCharterType.Self,BuildingType.Self)` | right_click_menu.gui |
|  | 直达 | `Company.ToggleCharter` | `Company.ToggleCharter(CompanyCharterType.Self)` | company_panel.gui |
|  | 直达 | `Company.ToggleRegionCharter` | `Company.ToggleRegionCharter(CompanyCharterType.Self,StateRegion.Self)` | right_click_menu.gui |
|  | 直达 | `ConstructionQueueElement.CancelConstruction` | `ConstructionQueueElement.CancelConstruction` | construction_queue.gui |
|  | 直达 | `ConstructionQueueElement.MoveDown` | `ConstructionQueueElement.MoveDown` | construction_queue.gui |
|  | 直达 | `ConstructionQueueElement.MoveToBottom` | `ConstructionQueueElement.MoveToBottom` | construction_queue.gui |
|  | 直达 | `ConstructionQueueElement.MoveToTop` | `ConstructionQueueElement.MoveToTop` | construction_queue.gui |
|  | 直达 | `ConstructionQueueElement.MoveUp` | `ConstructionQueueElement.MoveUp` | construction_queue.gui |
|  | 直达 | `Decree.GetRemoveCommand` | `Decree.GetRemoveCommand` | right_click_menu.gui, states_panel.gui |
|  | 直达 | `DecreeType.GetSetCommand` | `DecreeType.GetSetCommand(State.Self)` | right_click_menu.gui |
|  | 直达 | `Global.ChangeAllConstructionSpeed` | `ChangeAllConstructionSpeed(ProductionMethod.Self)` | budget_panel.gui |
|  | 直达 | `Global.PauseAllConstruction` | `PauseAllConstruction` | budget_panel.gui |
|  | 直达 | `Global.ResumeAllConstruction` | `ResumeAllConstruction` | budget_panel.gui |
|  | 直达 | `Goods.SetExportSubventionsHigh` | `Goods.GetMarket.GetOwner.SetExportSubventionsHigh(Goods.Self)` | budget_panel.gui |
|  | 直达 | `Goods.SetExportSubventionsLow` | `Goods.GetMarket.GetOwner.SetExportSubventionsLow(Goods.Self)` | budget_panel.gui |
|  | 直达 | `Goods.SetExportSubventionsMax` | `Goods.GetMarket.GetOwner.SetExportSubventionsMax(Goods.Self)` | budget_panel.gui |
|  | 直达 | `Goods.SetExportTariffsHigh` | `Goods.GetMarket.GetOwner.SetExportTariffsHigh(Goods.Self)` | budget_panel.gui |
|  | 直达 | `Goods.SetExportTariffsLow` | `Goods.GetMarket.GetOwner.SetExportTariffsLow(Goods.Self)` | budget_panel.gui |
|  | 直达 | `Goods.SetExportTariffsMax` | `Goods.GetMarket.GetOwner.SetExportTariffsMax(Goods.Self)` | budget_panel.gui |
|  | 直达 | `Goods.SetExportTariffsNone` | `Goods.GetMarket.GetOwner.SetExportTariffsNone(Goods.Self)` | budget_panel.gui |
|  | 直达 | `Goods.SetImportSubventionsHigh` | `Goods.GetMarket.GetOwner.SetImportSubventionsHigh(Goods.Self)` | budget_panel.gui |
|  | 直达 | `Goods.SetImportSubventionsLow` | `Goods.GetMarket.GetOwner.SetImportSubventionsLow(Goods.Self)` | budget_panel.gui |
|  | 直达 | `Goods.SetImportSubventionsMax` | `Goods.GetMarket.GetOwner.SetImportSubventionsMax(Goods.Self)` | budget_panel.gui |
|  | 直达 | `Goods.SetImportTariffsHigh` | `Goods.GetMarket.GetOwner.SetImportTariffsHigh(Goods.Self)` | budget_panel.gui |
|  | 直达 | `Goods.SetImportTariffsLow` | `Goods.GetMarket.GetOwner.SetImportTariffsLow(Goods.Self)` | budget_panel.gui |
|  | 直达 | `Goods.SetImportTariffsMax` | `Goods.GetMarket.GetOwner.SetImportTariffsMax(Goods.Self)` | budget_panel.gui |
|  | 直达 | `Goods.SetImportTariffsNone` | `Goods.GetMarket.GetOwner.SetImportTariffsNone(Goods.Self)` | budget_panel.gui |
|  | 直达 | `Goods.ToggleTaxation` | `Goods.ToggleTaxation(GetPlayer)` | add_consumption_tax_menu.gui, goods_panel.gui … |
|  | 直达 | `State.AbandonColony` | `State.AbandonColony` | states_panel.gui |
|  | 直达 | `State.Colonize` | `State.GetStateRegion.Colonize` | right_click_menu.gui |
|  | 直达 | `State.GetStationSelectedFormationsCommand` | `State.GetStationSelectedFormationsCommand` | right_click_menu.gui |
|  | 直达 | `State.IncorporateState` | `State.IncorporateState` | right_click_menu.gui, states_panel.gui |
|  | 直达 | `State.TogglePauseColonization` | `State.TogglePauseColonization` | states_panel.gui |
|  | 直达 | `State.UnincorporateState` | `State.UnincorporateState` | right_click_menu.gui, states_panel.gui |
|  | 窗口 | `BuildingBrowserBuildingTypeItem.RemoveAllPrivatization` | `BuildingBrowserBuildingTypeItem.RemoveAllPrivatization` | right_click_menu.gui |
|  | 窗口 | `BuildingBrowserBuildingTypeItem.ToggleAllAutoExpand` | `BuildingBrowserBuildingTypeItem.ToggleAllAutoExpand` | building_details_panel.gui |
|  | 窗口 | `BuildingBrowserBuildingTypeItem.ToggleAllPrivatization` | `BuildingBrowserBuildingTypeItem.ToggleAllPrivatization` | building_details_panel.gui, right_click_menu.gui |
|  | 窗口 | `BuildingBrowserBuildingTypeItem.ToggleAllSubsidies` | `BuildingBrowserBuildingTypeItem.ToggleAllSubsidies` | building_details_panel.gui, production_methods.gui |

## 政治（2 / 9）

| 状态 | 可达性 | 命令 | 例子 | 界面文件 |
|---|---|---|---|---|
| ✓ `Actions.enact_law` | 直达 | `Law.StartEnacting` | `Law.StartEnacting` | custom_tooltip.gui, politics_panel_change_law.gui … |
| ✓ `Actions.reform_government` | 窗口 | `ReformGovernment.Confirm` | `ReformGovernment.Confirm` | politics_panel_reform_government.gui |
|  | 直达 | `Amendment.Repeal` | `Amendment.Repeal` | politics_panel_types.gui |
|  | 直达 | `Institution.StartChangingLevelTo` | `Institution.StartChangingLevelTo(InstitutionInvestmentLevel.GetLevel)` | politics_panel_institutions.gui |
|  | 直达 | `Institution.StopSizeChange` | `Institution.StopSizeChange` | politics_panel_institutions.gui |
|  | 直达 | `Law.StartImposing` | `Law.StartImposing` | right_click_menu.gui |
|  | 直达 | `Law.StopEnacting` | `Law.StopEnacting` | custom_tooltip.gui, politics_panel_change_law.gui … |
|  | 直达 | `PoliticalMovement.ToggleBolstering` | `PoliticalMovement.ToggleBolstering` | custom_tooltip.gui, political_movement_panel.gui … |
|  | 直达 | `PoliticalMovement.ToggleSuppression` | `PoliticalMovement.ToggleSuppression` | custom_tooltip.gui, political_movement_panel.gui … |

## 研究（1 / 5）

| 状态 | 可达性 | 命令 | 例子 | 界面文件 |
|---|---|---|---|---|
| ✓ `Actions.research` | 直达 | `Technology.Research` | `Technology.Research(GetPlayer.Self)` | custom_tooltip.gui, tech_tree.gui |
|  | 直达 | `Technology.AddToQueueWithUnlocks` | `Technology.AddToQueueWithUnlocks(GetPlayer.Self)` | custom_tooltip.gui, tech_tree.gui |
|  | 直达 | `Technology.RemoveFromQueue` | `Technology.RemoveFromQueue(GetPlayer.Self)` | tech_tree.gui |
|  | 直达 | `Technology.ResearchWithUnlocks` | `Technology.ResearchWithUnlocks(GetPlayer.Self)` | custom_tooltip.gui, tech_tree.gui |
|  | 窗口 | `TechTreeLine.Research` | `TechTreeLine.GetTargetTech.Research(GetPlayer.Self)` | tech_tree.gui |

## 人物（0 / 9）

| 状态 | 可达性 | 命令 | 例子 | 界面文件 |
|---|---|---|---|---|
|  | 直达 | `Character.AssignToFormation` | `Character.AssignToFormation(MilitaryFormation.Self)` | right_click_menu.gui |
|  | 直达 | `Character.GetPromoteCommand` | `Character.GetPromoteCommand` | character_panel.gui, right_click_menu.gui |
|  | 直达 | `Character.GetRecruitCommand` | `Character.GetRecruitCommand(MilitaryFormation.Self)` | right_click_menu.gui |
|  | 直达 | `Character.GetRecruitCommandNoFormation` | `Character.GetRecruitCommandNoFormation` | generate_character.gui |
|  | 直达 | `Character.RecruitCharacterNoFormation` | `Character.RecruitCharacterNoFormation` | generate_character.gui |
|  | 直达 | `Character.SelectOrder` | `Character.SelectOrder(CommanderOrderType.Self)` | right_click_menu.gui |
|  | 直达 | `Character.UnassignFromFormation` | `Character.UnassignFromFormation` | right_click_menu.gui |
|  | 窗口 | `RulerSelectionPopup.RandomizeRulersOffer` | `RulerSelectionPopup.RandomizeRulersOffer` | generate_character.gui |
|  | 窗口 | `RulerSelectionPopup.SetRulerCommand` | `RulerSelectionPopup.SetRulerCommand(Character.Self)` | generate_character.gui |

## 日志（0 / 3）

| 状态 | 可达性 | 命令 | 例子 | 界面文件 |
|---|---|---|---|---|
|  | 直达 | `Decision.TakeDecision` | `Decision.TakeDecision(GetPlayer)` | journal.gui |
|  | 直达 | `ScriptedButton.ExecuteEffect` | `ScriptedButton.ExecuteEffect` | journal_entry.gui |
|  | 直达 | `ScriptedGui.je_meiji_restoration_japanese_emperor_sgui` | `ScriptedGui.je_meiji_restoration_japanese_emperor_sgui` | journal_entry_widgets/ep2_japan_widgets.gui |

## 事件（0 / 1）

| 状态 | 可达性 | 命令 | 例子 | 界面文件 |
|---|---|---|---|---|
|  | 窗口 | `EventOption.Select` | `EventOption.Select` | eventwindow.gui |

## 外交（0 / 37）

| 状态 | 可达性 | 命令 | 例子 | 界面文件 |
|---|---|---|---|---|
|  | 直达 | `CountryFormation.FormCountry` | `CountryFormation.FormCountry(GetPlayer)` | country_formation_panel.gui |
|  | 直达 | `CountryFormation.SupportCandidate` | `CountryFormation.SupportCandidate(GetPlayer,Country.Self)` | country_formation_panel.gui |
|  | 直达 | `DiplomaticAction.ExecuteAction` | `DiplomaticAction.ExecuteAction` | country_panel.gui, power_bloc_panel.gui … |
|  | 直达 | `DiplomaticAction.ExecuteWithConfirmation` | `DiplomaticAction.ExecuteWithConfirmation` | country_panel.gui, power_bloc_panel.gui … |
|  | 直达 | `DiplomaticPlay.BeOnTheFence` | `DiplomaticPlay.BeOnTheFence(GetPlayer)` | diplomatic_play_panel.gui |
|  | 直达 | `DiplomaticPlay.DeclareNeutrality` | `DiplomaticPlay.DeclareNeutrality(GetPlayer)` | diplomatic_play_panel.gui, right_click_menu.gui |
|  | 直达 | `DiplomaticPlay.LeanTowardsInitiator` | `DiplomaticPlay.LeanTowardsInitiator(GetPlayer)` | diplomatic_play_panel.gui |
|  | 直达 | `DiplomaticPlay.LeanTowardsTarget` | `DiplomaticPlay.LeanTowardsTarget(GetPlayer)` | diplomatic_play_panel.gui |
|  | 直达 | `DiplomaticPlay.SupportInitiator` | `DiplomaticPlay.SupportInitiator(GetPlayer)` | right_click_menu.gui, sway_country_panel.gui |
|  | 直达 | `DiplomaticPlay.SupportTarget` | `DiplomaticPlay.SupportTarget(GetPlayer)` | right_click_menu.gui, sway_country_panel.gui |
|  | 直达 | `DiplomaticPlay.SwitchSide` | `DiplomaticPlay.SwitchSide(GetPlayer)` | diplomatic_play_panel.gui, right_click_menu.gui |
|  | 直达 | `DiplomaticPlay.Yield` | `DiplomaticPlay.Yield(GetPlayer)` | diplomatic_play_panel.gui, right_click_menu.gui |
|  | 直达 | `DiplomaticPlayType.GetStartCommandCountry` | `DiplomaticPlayType.GetStartCommandCountry(GetPlayer.Self,Country.Self)` | country_panel.gui |
|  | 直达 | `DiplomaticPlayType.GetStartCommandState` | `DiplomaticPlayType.GetStartCommandState(GetPlayer,State.Self)` | country_panel.gui |
|  | 直达 | `PowerBloc.Kick` | `PowerBloc.Kick(Country.Self)` | power_bloc_panel.gui |
|  | 直达 | `PowerBlocPrinciple.UpgradeToNextLevel` | `PowerBlocPrinciple.UpgradeToNextLevel` | custom_tooltip.gui, power_bloc_panel.gui |
|  | 直达 | `Proposal.AcceptActionProposal` | `Proposal.GetDiplomaticAction.AcceptActionProposal` | popups.gui |
|  | 直达 | `Proposal.AcceptDiplomaticDemand` | `Proposal.GetDiplomaticDemand.AcceptDiplomaticDemand` | popups.gui |
|  | 直达 | `Proposal.AcceptSway` | `Proposal.GetDiplomaticPlay.GetIncomingSway(Proposal.GetActor.Self,Proposal.GetRecipient.Self).AcceptSway` | popups.gui |
|  | 直达 | `Proposal.AcceptTreatyProposal` | `Proposal.GetTreaty.AcceptTreatyProposal` | popups.gui |
|  | 直达 | `Proposal.DeclineActionProposal` | `Proposal.GetDiplomaticAction.DeclineActionProposal` | popups.gui |
|  | 直达 | `Proposal.DeclineTreatyProposal` | `Proposal.GetTreaty.DeclineTreatyProposal` | popups.gui |
|  | 直达 | `Proposal.RejectDiplomaticDemand` | `Proposal.GetDiplomaticDemand.RejectDiplomaticDemand` | popups.gui |
|  | 直达 | `Proposal.RejectSway` | `Proposal.GetDiplomaticPlay.GetIncomingSway(Proposal.GetActor.Self,Proposal.GetRecipient.Self).RejectSway` | popups.gui |
|  | 直达 | `Treaty.WithdrawFromTreaty` | `Treaty.WithdrawFromTreaty` | treaty_panel.gui |
|  | 直达 | `WarGoal.MakeWarGoalPrimaryDemand` | `WarGoal.MakeWarGoalPrimaryDemand(GetPlayer.Self)` | diplomatic_play_panel.gui |
|  | 直达 | `WarGoal.ToggleIsPressedInPotentialPeaceDeal` | `WarGoal.ToggleIsPressedInPotentialPeaceDeal(GetPlayer.Self)` | add_wargoal_panel.gui, map_markers.gui |
|  | 窗口 | `AddWarGoalPanel.AddWarGoal` | `AddWarGoalPanel.AccessDiplomaticPlay.AddWarGoal(WarGoalDraft.Self)` | add_wargoal_panel.gui |
|  | 窗口 | `DiplomaticActionWindow.ExecuteAction` | `DiplomaticActionWindow.ExecuteAction` | popups.gui |
|  | 窗口 | `DiplomaticPlayConfirmation.ConfirmAction` | `DiplomaticPlayConfirmation.ConfirmAction` | popups.gui |
|  | 窗口 | `PowerBlocFormation.Confirm` | `PowerBlocFormation.Confirm` | power_bloc_formation_panel.gui |
|  | 窗口 | `PowerBlocPrincipleSelectionWindow.SubmitPrincipleSelection` | `PowerBlocPrincipleSelectionWindow.SubmitPrincipleSelection` | principle_selection_window.gui |
|  | 窗口 | `ReleaseCountryWindow.ReleaseCountry` | `ReleaseCountryWindow.ReleaseCountry` | popups.gui |
|  | 窗口 | `SwayCountryPanel.CreateSway` | `SwayCountryPanel.AccessDiplomaticPlay.CreateSway(GetPlayer.Self,SwayCountryPanel.GetCountry,SwayOffer.Self)` | right_click_menu.gui, sway_country_panel.gui |
|  | 窗口 | `TreatyDraft.SendProposal` | `TreatyDraft.SendProposal` | treaty_draft_panel.gui |
|  | 窗口 | `WarGoalDraft.AddTreatyWarGoal` | `WarGoalDraft.GetDiplomaticPlay.AddTreatyWarGoal(WarGoalDraft.Self,ArticleDraft.Self)` | right_click_menu.gui |
|  | 窗口 | `WarGoalDraft.AddWarGoal` | `WarGoalDraft.GetDiplomaticPlay.AddWarGoal(WarGoalDraft.Self)` | right_click_menu.gui |

## 军事（0 / 90）

| 状态 | 可达性 | 命令 | 例子 | 界面文件 |
|---|---|---|---|---|
|  | 直达 | `War.ToggleAcceptPeace` | `War.ToggleAcceptPeace(GetPlayer.Self)` | war_panel.gui |
|  | 窗口 | `DecommissionSupplyShipsWindow.GetDecommissionCommand` | `DecommissionSupplyShipsWindow.GetDecommissionCommand` | popups.gui |
|  | 窗口 | `InvasionPlannerPopup.StartInvasion` | `InvasionPlannerPopup.StartInvasion` | invasion_planner.gui |
|  | 窗口 | `PanelMilitary.GetUpgradeAllUnitsInAllFormationsCommand` | `PanelMilitary.GetUpgradeAllUnitsInAllFormationsCommand` | panel_military.gui |
|  | 窗口 | `ShipDesignerPopup.CreateTemplate` | `ShipDesignerPopup.CreateTemplate` | ship_designer_popup.gui |
|  | 窗口 | `ShipDesignerPopup.EditTemplate` | `ShipDesignerPopup.EditTemplate` | ship_designer_popup.gui |
|  | 窗口 | `TransferFormationPopup.Confirm` | `TransferFormationPopup.Confirm` | transfer_formation.gui |
|  | 窗口 | `TransportPlannerPopup.GetTransportCommand` | `TransportPlannerPopup.GetTransportCommand(MilitaryFormation.Self)` | right_click_menu.gui |
|  | 窗口 | `TransportPlannerPopup.StartTransport` | `TransportPlannerPopup.StartTransport` | transport_planner.gui |
|  | 窗口 | `WarPanel.Capitulate` | `WarPanel.GetWar.Capitulate(GetPlayer.Self)` | war_panel.gui |
|  | 窗口 | `WarPanel.ProposePeaceDeal` | `WarPanel.GetWar.ProposePeaceDeal(GetPlayer.Self)` | war_panel.gui |
|  | 窗口 | `WarPanel.SetWhitePeace` | `WarPanel.GetWar.SetWhitePeace(GetPlayer.Self)` | war_panel.gui |
|  | 组合 | `CombatUnit.GetDisbandUnitCommand` | `CombatUnit.GetMilitaryFormation.GetDisbandUnitCommand(CombatUnit.Self)` | military_formation_panel.gui |
|  | 组合 | `Front.GetDeploySelectedFormationsCommand` | `Front.GetDeploySelectedFormationsCommand` | map_markers.gui |
|  | 组合 | `Global.CancelRetrofitShips` | `CancelRetrofitShips` | construction_panel.gui |
|  | 组合 | `Global.CreateNavalMissionsForSelectedFleets` | `CreateNavalMissionsForSelectedFleets(NavalMissionType.AccessSelf)` | right_click_menu.gui |
|  | 组合 | `Global.DemobilizeSelectedArmies` | `DemobilizeSelectedArmies` | military_formation_panel.gui |
|  | 组合 | `Global.MergeSelectedFormations` | `MergeSelectedFormations` | military_formation_panel.gui |
|  | 组合 | `Global.MobilizeSelectedArmies` | `MobilizeSelectedArmies` | military_formation_panel.gui |
|  | 组合 | `Global.RaiseConscriptsInSelectedArmies` | `RaiseConscriptsInSelectedArmies` | military_formation_panel.gui |
|  | 组合 | `Global.RemoveNavalMissionForSelectedFleets` | `RemoveNavalMissionForSelectedFleets(NavalMissionType.Self)` | right_click_menu.gui |
|  | 组合 | `Global.RetrofitShips` | `RetrofitShips` | construction_panel.gui, right_click_menu.gui |
|  | 组合 | `Global.RetrofitShipsAndStation` | `RetrofitShipsAndStation` | right_click_menu.gui |
|  | 组合 | `Global.SetCharacterOrderForSelectedFormations` | `SetCharacterOrderForSelectedFormations(CommanderOrderType.Self)` | military_formation_panel.gui |
|  | 组合 | `Global.SetStrategicObjectiveForSelectedFormations` | `SetStrategicObjectiveForSelectedFormations(State.Self)` | right_click_menu.gui |
|  | 组合 | `Hq.GetStationSelectedFormationsCommand` | `Hq.GetStationSelectedFormationsCommand` | map_markers.gui |
|  | 组合 | `Invasion.Cancel` | `Invasion.Cancel` | invasion_panel.gui, military_formation_panel.gui … |
|  | 组合 | `Invasion.DeployArmyToDefend` | `Invasion.DeployArmyToDefend(MilitaryFormation.Self)` | right_click_menu.gui |
|  | 组合 | `Invasion.DeployFleetToDefend` | `Invasion.DeployFleetToDefend(MilitaryFormation.Self)` | right_click_menu.gui |
|  | 组合 | `Invasion.GetDeploySelectedFormationsCommand` | `Invasion.GetDeploySelectedFormationsCommand` | map_markers.gui |
|  | 组合 | `MilitaryFormation.CancelRetrofitShips` | `MilitaryFormation.CancelRetrofitShips` | military_panel_formations.gui |
|  | 组合 | `MilitaryFormation.CreateNavalMission` | `MilitaryFormation.CreateNavalMission(NavalMissionType.AccessSelf)` | right_click_menu.gui |
|  | 组合 | `MilitaryFormation.CreateNavalMissionWithPreviousArea` | `MilitaryFormation.CreateNavalMissionWithPreviousArea(NavalMissionType.AccessSelf)` | right_click_menu.gui |
|  | 组合 | `MilitaryFormation.Demobilize` | `MilitaryFormation.Demobilize` | military_formation_panel.gui, right_click_menu.gui |
|  | 组合 | `MilitaryFormation.Disband` | `MilitaryFormation.Disband` | military_formation_panel.gui, military_panel_formations.gui … |
|  | 组合 | `MilitaryFormation.DisembarkFormation` | `MilitaryFormation.DisembarkFormation` | right_click_menu.gui |
|  | 组合 | `MilitaryFormation.GetDisbandUnitTypeConscriptCommand` | `MilitaryFormation.GetDisbandUnitTypeConscriptCommand(CombatUnitType.Self)` | military_formation_panel.gui |
|  | 组合 | `MilitaryFormation.GetDisbandUnitTypeRegularCommand` | `MilitaryFormation.GetDisbandUnitTypeRegularCommand(CombatUnitType.Self)` | military_formation_panel.gui |
|  | 组合 | `MilitaryFormation.GetSetDefaultUnitTypeCommand` | `MilitaryFormation.GetSetDefaultUnitTypeCommand(CombatUnitType.Self)` | military_formation_panel.gui |
|  | 组合 | `MilitaryFormation.GetUpgradeConscriptUnitTypeCommand` | `MilitaryFormation.GetUpgradeConscriptUnitTypeCommand(MilitaryFormationUnitEntry.GetUnitType.Self)` | military_formation_panel.gui |
|  | 组合 | `MilitaryFormation.GetUpgradeRegularUnitTypeCommand` | `MilitaryFormation.GetUpgradeRegularUnitTypeCommand(MilitaryFormationUnitEntry.GetUnitType.Self)` | military_formation_panel.gui |
|  | 组合 | `MilitaryFormation.GetUpgradeUnitGroupCommand` | `MilitaryFormation.GetUpgradeUnitGroupCommand(CombatUnitGroup.Self)` | military_formation_panel.gui |
|  | 组合 | `MilitaryFormation.Mobilize` | `MilitaryFormation.Mobilize` | military_formation_panel.gui, panel_military.gui … |
|  | 组合 | `MilitaryFormation.RaiseConscripts` | `MilitaryFormation.RaiseConscripts` | military_formation_panel.gui, right_click_menu.gui |
|  | 组合 | `MilitaryFormation.RecallForRepairs` | `MilitaryFormation.RecallForRepairs` | right_click_menu.gui |
|  | 组合 | `MilitaryFormation.RemoveNavalMission` | `MilitaryFormation.RemoveNavalMission` | right_click_menu.gui |
|  | 组合 | `MilitaryFormation.RetrofitShips` | `MilitaryFormation.RetrofitShips` | military_panel_formations.gui, right_click_menu.gui |
|  | 组合 | `MilitaryFormation.RetrofitShipsAndStation` | `MilitaryFormation.RetrofitShipsAndStation` | right_click_menu.gui |
|  | 组合 | `MilitaryFormation.SelectSupplyPriority` | `MilitaryFormation.SelectSupplyPriority('low')` | military_formation_panel.gui |
|  | 组合 | `MilitaryFormationBorrowSetting.GetBorrowingCommand` | `MilitaryFormationBorrowSetting.GetBorrowingCommand` | military_formation_panel.gui |
|  | 组合 | `MilitaryFormationWrapped.EmbarkFormation` | `MilitaryFormationWrapped.EmbarkFormation(MilitaryFormation.Self)` | right_click_menu.gui |
|  | 组合 | `MobilizationOption.Toggle` | `MobilizationOption.Toggle(MilitaryFormation.AccessSelf)` | military_formation_panel.gui, panel_military.gui |
|  | 组合 | `MobilizationOption.ToggleForSelected` | `MobilizationOption.ToggleForSelected` | military_formation_panel.gui |
|  | 组合 | `SeaNodeMovementMarker.AddSeaRegionToSelectedFleetMissions` | `SeaNodeMovementMarker.GetSeaNode.AddSeaRegionToSelectedFleetMissions` | map_markers.gui |
|  | 组合 | `SeaNodeMovementMarker.AssignSelectedFleetsToNewMissionInRegion` | `SeaNodeMovementMarker.GetSeaNode.AssignSelectedFleetsToNewMissionInRegion(GetDefine('NMilitary','NAVAL_MISSION_TYPE_PROJECT_POWER'))` | map_markers.gui |
|  | 组合 | `Ship.AssignAsFlagship` | `Ship.AssignAsFlagship` | ship_panel.gui |
|  | 组合 | `Ship.CancelRetrofit` | `Ship.CancelRetrofit` | combat_unit_types.gui, ship_panel.gui |
|  | 组合 | `Ship.ChangeTemplate` | `Ship.ChangeTemplate(ShipTemplate.Self)` | right_click_menu.gui |
|  | 组合 | `Ship.Decommission` | `Ship.Decommission` | ship_panel.gui |
|  | 组合 | `Ship.Retrofit` | `Ship.Retrofit` | combat_unit_types.gui, ship_panel.gui |
|  | 组合 | `Ship.SetNextFlagshipOrnament` | `Ship.SetNextFlagshipOrnament` | ship_panel.gui |
|  | 组合 | `Ship.SetPrevFlagshipOrnament` | `Ship.SetPrevFlagshipOrnament` | ship_panel.gui |
|  | 组合 | `Ship.ToggleFlagshipSignalFlags` | `Ship.ToggleFlagshipSignalFlags` | ship_panel.gui |
|  | 组合 | `Ship.UnassignAsFlagship` | `Ship.UnassignAsFlagship` | ship_panel.gui |
|  | 组合 | `ShipConstruction.Cancel` | `ShipConstruction.Cancel` | construction_panel.gui |
|  | 组合 | `ShipConstruction.MoveDown` | `ShipConstruction.MoveDown` | construction_panel.gui |
|  | 组合 | `ShipConstruction.MoveToBottom` | `ShipConstruction.MoveToBottom` | construction_panel.gui |
|  | 组合 | `ShipConstruction.MoveToTop` | `ShipConstruction.MoveToTop` | construction_panel.gui |
|  | 组合 | `ShipConstruction.MoveUp` | `ShipConstruction.MoveUp` | construction_panel.gui |
|  | 组合 | `ShipSelection.ChangeTemplate` | `ShipSelection.ChangeTemplate(ShipTemplate.Self)` | right_click_menu.gui |
|  | 组合 | `ShipSelection.Decommission` | `ShipSelection.Decommission` | combat_unit_types.gui |
|  | 组合 | `ShipSelection.Retrofit` | `ShipSelection.Retrofit` | combat_unit_types.gui |
|  | 组合 | `ShipTemplate.CancelConstruction` | `ShipTemplate.CancelConstruction` | right_click_menu.gui |
|  | 组合 | `ShipTemplate.CancelConstructionForFleet` | `ShipTemplate.CancelConstructionForFleet(MilitaryFormation.Self)` | right_click_menu.gui |
|  | 组合 | `ShipTemplate.DeleteTemplate` | `ShipTemplate.DeleteTemplate` | right_click_menu.gui |
|  | 组合 | `ShipTemplate.QueueConstruction` | `ShipTemplate.QueueConstruction` | right_click_menu.gui |
|  | 组合 | `ShipTemplate.QueueConstructionForFleet` | `ShipTemplate.QueueConstructionForFleet(MilitaryFormation.Self)` | right_click_menu.gui |
|  | 组合 | `ShipTemplate.SetAsDefaultForCountry` | `ShipTemplate.SetAsDefaultForCountry` | right_click_menu.gui |
|  | 组合 | `ShipTemplate.SetAsDefaultForFleet` | `ShipTemplate.SetAsDefaultForFleet(MilitaryFormation.Self)` | right_click_menu.gui |
|  | 组合 | `Strait.SetControllerTollRateHighTolls` | `Strait.SetControllerTollRateHighTolls(Country.Self)` | strait_panel.gui |
|  | 组合 | `Strait.SetControllerTollRateLowTolls` | `Strait.SetControllerTollRateLowTolls(Country.Self)` | strait_panel.gui |
|  | 组合 | `Strait.SetControllerTollRateMediumTolls` | `Strait.SetControllerTollRateMediumTolls(Country.Self)` | strait_panel.gui |
|  | 组合 | `Strait.SetControllerTollRateNoTolls` | `Strait.SetControllerTollRateNoTolls(Country.Self)` | strait_panel.gui |
|  | 组合 | `Strait.SetStateAccessClosed` | `Strait.SetStateAccessClosed(State.Self)` | strait_panel.gui |
|  | 组合 | `Strait.SetStateAccessNoMilitary` | `Strait.SetStateAccessNoMilitary(State.Self)` | strait_panel.gui |
|  | 组合 | `Strait.SetStateAccessOpen` | `Strait.SetStateAccessOpen(State.Self)` | strait_panel.gui |
|  | 组合 | `Strait.SetStateAllowedCountriesNoEnemies` | `Strait.SetStateAllowedCountriesNoEnemies(State.Self)` | strait_panel.gui |
|  | 组合 | `Strait.SetStateAllowedCountriesOnlyAllies` | `Strait.SetStateAllowedCountriesOnlyAllies(State.Self)` | strait_panel.gui |
|  | 组合 | `Strait.SetStateAllowedCountriesOnlyController` | `Strait.SetStateAllowedCountriesOnlyController(State.Self)` | strait_panel.gui |
|  | 界面 | `GetDraggedDatacontext.MoveToIndex` | `GetDraggedDatacontext('ShipConstruction').MoveToIndex(ShipConstruction.GetIndex)` | construction_panel.gui, construction_queue.gui |

## 其他（0 / 5）

| 状态 | 可达性 | 命令 | 例子 | 界面文件 |
|---|---|---|---|---|
|  | 窗口 | `StateNameChangePopup.Confirm` | `StateNameChangePopup.Confirm` | states_panel.gui |
|  | 界面 | `CompanyChangeNamePopup.Confirm` | `CompanyChangeNamePopup.Confirm` | companies_panel.gui |
|  | 界面 | `MilitaryFormationChangeNamePopup.Confirm` | `MilitaryFormationChangeNamePopup.Confirm` | military_formation_panel.gui |
|  | 界面 | `PrestigeGoodChangeNamePopup.Confirm` | `PrestigeGoodChangeNamePopup.Confirm` | market_panel.gui |
|  | 界面 | `ShipChangeNamePopup.Confirm` | `ShipChangeNamePopup.Confirm` | ship_panel.gui |

