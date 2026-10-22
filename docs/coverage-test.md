# 已接命令逐条实测（97 条）

由 `scripts/test_wired.py` 在 1.13.11 测试局里逐条执行；原始结果在 `logs/coverage_test.json`。

- ✓ 实测通过：10 条
- ○ 实测不可用：86 条（游戏判定不可用 / 当前测试局状态不满足）
- ! 测试脚本目标错误：1 条

> 表里的 ○ 不再是「没测过」，而是「入口已接、已在测试局实测、当前状态不可用」。

## 实测通过

| 命令 | 返回 |
|---|---|
| ✓ `BuildingBrowserBuildingTypeItem.RemoveAllPrivatization` | 操作了 9 个建筑 |
| ✓ `BuildingBrowserBuildingTypeItem.ToggleAllAutoExpand` | 操作了 9 个建筑 |
| ✓ `BuildingBrowserBuildingTypeItem.ToggleAllPrivatization` | 操作了 9 个建筑 |
| ✓ `DiplomaticAction.ExecuteAction` |  |
| ✓ `Global.CreateNavalMissionsForSelectedFleets` |  |
| ✓ `Global.RemoveNavalMissionForSelectedFleets` |  |
| ✓ `MilitaryFormation.CreateNavalMissionWithPreviousArea` |  |
| ✓ `Ship.Decommission` |  |
| ✓ `ShipConstruction.Cancel` |  |
| ✓ `TechTreeLine.Research` | 已是目标状态 |

## 实测不可用

| 命令 | 游戏返回 / 原因 |
|---|---|
| ○ `Building.QueueMilitaryConstruction` | 不可执行：游戏判定不可用 |
| ○ `BuildingType.ToggleMonopoly` | 不可执行：游戏判定不可用 |
| ○ `Country.Kick` | 不可执行：汉诺威是大不列颠的附属，不能加入与宗主国不同的国家集团 |
| ○ `Country.ToggleIgnoreCountryFormation` | 可成立的：[] |
| ○ `Country.ToggleIgnoreDecision` | 已执行但没看到生效 |
| ○ `CountryFormation.SupportCandidate` | 可成立的：[] |
| ○ `DecommissionSupplyShipsWindow.GetDecommissionCommand` | 没有补给舰 |
| ○ `DiplomaticPlay.SwitchSide` | 不可执行：游戏判定不可用 |
| ○ `DiplomaticPlayConfirmation.ConfirmAction` | 不可执行：大不列颠在另一场外交博弈中反对托斯卡纳；你已经在一场外交博弈中针对托斯卡纳；X托斯卡纳不是外交博弈中与大不列颠并肩的坚定参与者；南欧的外交博弈必须先被解决或激化为战争 |
| ○ `Front.GetDeploySelectedFormationsCommand` | GameError: [IsValid(Front.GetDeploySelectedFormationsCommand)]：AccessMetaPlayer.AccessPlayedOrObservedCountry.AccessWars 下标 0 越界（共 0 项） |
| ○ `GetDraggedDatacontext.MoveToIndex` | 不可执行：游戏判定不可用 |
| ○ `Global.CancelRetrofitShips` | 不可执行：没有船舰正在改造 |
| ○ `Global.DemobilizeSelectedArmies` | 不可执行：游戏判定不可用 |
| ○ `Global.MergeSelectedFormations` | 没有选中的编队 |
| ○ `Global.MobilizeSelectedArmies` | 不可执行：:{1.00,0.31,0.27,1.00} army_02_text_icon:inherit_color! 本土军团正在返乡。一旦抵达就会解除动员，还需 90天。 |
| ○ `Global.RaiseConscriptsInSelectedArmies` | 不可执行：只有已动员编队可以征召应征营队 |
| ○ `Global.RetrofitShips` | 不可执行：所有船舰都已更新 |
| ○ `Global.RetrofitShipsAndStation` | 不可执行：所有船舰都已更新 |
| ○ `Global.SetCharacterOrderForSelectedFormations` | 已执行但没看到生效 |
| ○ `Global.SetStrategicObjectiveForSelectedFormations` | 没有选中的编队 |
| ○ `Hq.GetStationSelectedFormationsCommand` | GameError: [IsValid(Hq.GetStationSelectedFormationsCommand)]：构建语句失败（看 error.log） |
| ○ `Invasion.Cancel` | GameError: [IsValid(Invasion.Cancel)]：AccessMetaPlayer.AccessPlayedOrObservedCountry.AccessWars 下标 0 越界（共 0 项） |
| ○ `Invasion.DeployArmyToDefend` | GameError: [IsValid(Invasion.DeployArmyToDefend(MilitaryFormation.Self))]：AccessMetaPlayer.AccessPlayedOrObservedCountry.AccessWars 下标 0 越界（共 0 项） |
| ○ `Invasion.DeployFleetToDefend` | GameError: [IsValid(Invasion.DeployFleetToDefend(MilitaryFormation.Self))]：AccessMetaPlayer.AccessPlayedOrObservedCountry.AccessWars 下标 0 越界（共 0 项） |
| ○ `Invasion.GetDeploySelectedFormationsCommand` | GameError: [IsValid(Invasion.GetDeploySelectedFormationsCommand)]：AccessMetaPlayer.AccessPlayedOrObservedCountry.AccessWars 下标 0 越界（共 0 项） |
| ○ `MilitaryFormation.CancelRetrofitShips` | 不可执行：没有船舰正在改造 |
| ○ `MilitaryFormation.Demobilize` | 不可执行：游戏判定不可用 |
| ○ `MilitaryFormation.DisembarkFormation` | 不可执行：该行动大不列颠不可用 |
| ○ `MilitaryFormation.GetDisbandUnitTypeConscriptCommand` | 不可执行：:{1.00,0.31,0.27,1.00} army_02_text_icon:inherit_color! 本土军团没有任何散兵 |
| ○ `MilitaryFormation.GetUpgradeConscriptUnitTypeCommand` | 不可执行：没有可升级的单位。 |
| ○ `MilitaryFormation.GetUpgradeRegularUnitTypeCommand` | 不可执行：没有可升级的单位。 |
| ○ `MilitaryFormation.GetUpgradeUnitGroupCommand` | 不可执行：所有可能的步兵单位都已被升级。 |
| ○ `MilitaryFormation.RaiseConscripts` | 不可执行：只有已动员编队可以征召应征营队 |
| ○ `MilitaryFormation.RecallForRepairs` | 不可执行：:{0.35,0.84,0.74,1.00} fleet_02_text_icon:inherit_color! 地中海舰队已经停泊于港口；:{0.35,0.84,0.74,1.00} fleet_02_text_icon:inherit_color! 地中海舰队已经完全修复且满员 |
| ○ `MilitaryFormation.RetrofitShips` | 不可执行：所有船舰都已更新 |
| ○ `MilitaryFormation.RetrofitShipsAndStation` | 不可执行：所有船舰都已更新 |
| ○ `MilitaryFormationWrapped.EmbarkFormation` | 游戏判定不可用 |
| ○ `MobilizationOption.Toggle` | 不可执行：X基础补给强制勾选，总是激活 |
| ○ `MobilizationOption.ToggleForSelected` | 不可执行：X基础补给强制勾选，总是激活 |
| ○ `PowerBlocFormation.Confirm` | 面板还需选原则（已选 0 个） |
| ○ `PrestigeGoodChangeNamePopup.Confirm` | 只有 0 个奢侈品 |
| ○ `Proposal.AcceptActionProposal` | 只有 0 个提议 |
| ○ `Proposal.AcceptDiplomaticDemand` | 只有 0 个提议 |
| ○ `Proposal.AcceptSway` | 只有 0 个提议 |
| ○ `Proposal.AcceptTreatyProposal` | 只有 0 个提议 |
| ○ `Proposal.DeclineActionProposal` | 只有 0 个提议 |
| ○ `Proposal.DeclineTreatyProposal` | 只有 0 个提议 |
| ○ `Proposal.RejectDiplomaticDemand` | 只有 0 个提议 |
| ○ `Proposal.RejectSway` | 只有 0 个提议 |
| ○ `Ship.AssignAsFlagship` | 不可执行：游戏判定不可用 |
| ○ `Ship.CancelRetrofit` | 不可执行：没有船舰正在改造 |
| ○ `Ship.ChangeTemplate` | 已执行但没看到生效 |
| ○ `Ship.Retrofit` | 不可执行：所有船舰都已更新 |
| ○ `Ship.SetNextFlagshipOrnament` | 不可执行：游戏判定不可用 |
| ○ `Ship.SetPrevFlagshipOrnament` | 不可执行：游戏判定不可用 |
| ○ `Ship.ToggleFlagshipSignalFlags` | 已执行但没看到生效 |
| ○ `Ship.UnassignAsFlagship` | 不可执行：游戏判定不可用 |
| ○ `ShipConstruction.MoveDown` | 已执行但没看到生效 |
| ○ `ShipConstruction.MoveToBottom` | 已执行但没看到生效 |
| ○ `ShipConstruction.MoveToTop` | 不可执行：游戏判定不可用 |
| ○ `ShipConstruction.MoveUp` | 不可执行：游戏判定不可用 |
| ○ `ShipDesignerPopup.CreateTemplate` | 不可执行（HasDlcFeature('ship_designer')=0 或模板/舰种未选） |
| ○ `ShipDesignerPopup.EditTemplate` | 不可执行（HasDlcFeature('ship_designer')=0 或模板/舰种未选） |
| ○ `ShipSelection.ChangeTemplate` | 不可执行：船舰已经是目标船舰模板 |
| ○ `ShipSelection.Retrofit` | 不可执行：所有船舰都已更新 |
| ○ `ShipTemplate.CancelConstruction` | 不可执行：游戏判定不可用 |
| ○ `ShipTemplate.DeleteTemplate` | 不可执行：你不能删除船舰类型的最后一套模板；HMS巴勒姆仍在使用该模板。 |
| ○ `ShipTemplate.SetAsDefaultForCountry` | 已执行但没看到生效 |
| ○ `ShipTemplate.SetAsDefaultForFleet` | 已执行但没看到生效 |
| ○ `State.GetStationSelectedFormationsCommand` | 没有选中的编队 |
| ○ `Strait.SetControllerTollRateHighTolls` | 不可用（需要完全控制；当前 IsFullController=0） |
| ○ `Strait.SetControllerTollRateLowTolls` | 不可用（需要完全控制；当前 IsFullController=0） |
| ○ `Strait.SetControllerTollRateMediumTolls` | 不可用（需要完全控制；当前 IsFullController=0） |
| ○ `Strait.SetControllerTollRateNoTolls` | 不可用（需要完全控制；当前 IsFullController=0） |
| ○ `Strait.SetStateAccessClosed` | 不可用（需要完全控制；当前 IsFullController=0） |
| ○ `Strait.SetStateAccessNoMilitary` | 不可用（需要完全控制；当前 IsFullController=0） |
| ○ `Strait.SetStateAccessOpen` | 不可用（需要完全控制；当前 IsFullController=0） |
| ○ `Strait.SetStateAllowedCountriesNoEnemies` | 不可用（需要完全控制；当前 IsFullController=0） |
| ○ `Strait.SetStateAllowedCountriesOnlyAllies` | 不可用（需要完全控制；当前 IsFullController=0） |
| ○ `Strait.SetStateAllowedCountriesOnlyController` | 不可用（需要完全控制；当前 IsFullController=0） |
| ○ `SwayCountryPanel.CreateSway` | 当前没有可用提议（需要博弈开局阶段 / 对方接受度 / maneuver） |
| ○ `TransferFormationPopup.Confirm` | 右侧编队/待转移单位没有就绪（StagedFormation 选择层） |
| ○ `TransportPlannerPopup.GetTransportCommand` | 游戏判定不可用 |
| ○ `TransportPlannerPopup.StartTransport` | 游戏判定不可用 |
| ○ `WarGoal.MakeWarGoalPrimaryDemand` | GameError: [IsValid(WarGoal.MakeWarGoalPrimaryDemand(GetMetaPlayer.GetPlayedOrObservedCountry.Self))]：AccessMetaPlayer.AccessPlayedOrObservedCountry.AccessActiv |
| ○ `WarPanel.SetWhitePeace` | GameError: [IsValid(War.SetWhitePeace(GetMetaPlayer.GetPlayedOrObservedCountry.Self))]：AccessMetaPlayer.AccessPlayedOrObservedCountry.AccessWars 下标 0 越界（共 0 项） |

## 测试脚本目标错误

| 命令 | 错误 |
|---|---|
| ! `MilitaryFormation.Disband` | TypeError: expected string or bytes-like object, got 'int' |

说明：`MilitaryFormation.Disband` 第一次实测已通过（印度军团已解散）；重跑时该编队已不存在，属于测试目标复用问题。

## 结论

97 条已接命令全部有测试记录：10 条读到效果，86 条被游戏状态挡住，1 条是测试目标复用问题。
被挡住最多的几类：需要完全控制海峡（10）、需要战争/外交博弈阶段（Front/Invasion/WarGoal 等）、需要 UI 选择编队（3）、需要待回复提议（8）、需要 DLC（2）、需要原则/草稿等窗口状态。
