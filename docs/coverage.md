# 玩家操作覆盖进度

`docs/actions.md` 是从 `game/gui/**/*.gui` 抽出的全部玩家命令（266 条 / 226 种）。
本文件记录：哪些已经在游戏里跑通（✓）、哪些已经接到代码路径但当前测试局状态不满足（○）、
哪些还没接（空白），以及没接的原因。

刷新：`python tools/extract_actions.py`（读游戏目录，重写 `docs/actions.md` 与
`src/agent/data/actions.json`）。

## 当前进度（2026-10-22）

| 状态 | 命令数 | 说明 |
|---|---:|---|
| ✓ 已验证 | 172 | 在游戏里执行并读到效果（或等效状态变化） |
| ○ 已接（已实测·受限） | 86 | 入口已通且已逐条实测，当前测试局状态不满足（没有战争、没有 DLC、没有完全控制海峡……） |
| 未接 | 8 | 见下节 |

逐条实测：97 条已接全部跑过，10 条读到效果（已升 ✓），86 条被游戏状态挡住；
原始结果与每条原因见 [coverage-test.md](coverage-test.md)（`scripts/test_wired.py`，`logs/coverage_test.json`）。

## 今天新打通的入口

代码在 `src/agent/coverage.py`（`Coverage` 继承 `Actions`），MCP 的 `act` 已经指向它。

### 军事编队

| 动作 | 路径 |
|---|---|
| 选中补给优先级 | `MilitaryFormation.SelectSupplyPriority('low'/'medium'/'high')`，读 `IsSupplyPrioritySelected` |
| 默认单位类型 | `MilitaryFormation.GetSetDefaultUnitTypeCommand(MilitaryFormationUnitEntry.GetUnitType.Self)`，路径到 `GetCombatUnitEntries` 的一项；会重排条目，核实时按类型名重找 |
| 按类型解散 / 升级 | `GetDisbandUnitTypeRegularCommand` / `GetDisbandUnitTypeConscriptCommand` / `GetUpgradeRegularUnitTypeCommand` / `GetUpgradeConscriptUnitTypeCommand`，参数同上 |
| 按单位组升级 | `MilitaryFormation.GetUpgradeUnitGroupCommand(CombatUnitGroup.Self)`，路径到 `MilitaryFormation.GetEligibleGroups` |
| 单个战斗单位解散 | `CombatUnit.GetMilitaryFormation.GetDisbandUnitCommand(CombatUnit.Self)`，路径到 `MilitaryFormationUnitEntry.GetCombatUnits` |
| 动员 / 复员 / 征召 | `MilitaryFormation.Mobilize` / `Demobilize` / `RaiseConscripts`（动员要外交博弈或战争；征召要还没征召过） |
| 升级全部单位 | `MilitaryFormation.GetUpgradeAllUnitsCommand` |
| 补给舰退役 | 逐艘 `Ship.Decommission`（补给舰窗口的等价路径） |
| 军事建造 | `Building.QueueMilitaryConstruction(MilitaryFormation.Self, CombatUnitType.Self)`；测试局里英国没有征兵中心，命令收下但没有单位可造 |

### 舰船 / 模板 / 造船队列

- 全部舰船：`AccessMetaPlayer.AccessPlayedOrObservedCountry.GetShipList.GetShips`
- 某舰队：`MilitaryFormation.GetShipList.GetShips` + 路径到编队
- 模板：`ShipList.GetShipTemplates`；造船队列：`ShipList.GetShipConstructions`
- **舰船选择**：`AccessPlayer.GetShipList.GetActiveSelection.Self`。选择是**按 ShipGroup 分组的编辑模式**：

  ```
  路径 p0 = =AccessPlayer.GetShipList                i0 = 0
       p1 = AccessPlayer.GetShipList.GetShipGroups   i1 = 组下标
  执行 ShipList.ToggleEditMode(ShipGroup.Self)          # 进入该组的编辑模式
  再在 p0 = =AccessPlayer.GetShipList.GetActiveSelection.Self
       p1 = AccessPlayer.GetShipList.GetShips            # 对应组的舰船
  执行 ShipSelection.ToggleSelection(Ship.Self)         # 或 SelectFiltered
  执行 Execute(ShipSelection.Decommission)              # 退役选中的舰船
  ```
  不在编辑模式时 `GetActiveSelection` 返回空指针，语句会报 `Promote ... returned nullptr`。
- 模板命令：`ShipTemplate.QueueConstruction` / `QueueConstructionForFleet(MilitaryFormation.Self)` /
  `CancelConstructionForFleet` / `SetAsDefaultForCountry` / `SetAsDefaultForFleet`。
- 造船队列：`ShipConstruction.Cancel/MoveUp/MoveDown/MoveToTop/MoveToBottom/MoveToIndex`。

### 外交与战争

- 战争目标坚持 / 放弃：`WarGoal.ToggleIsPressedInPotentialPeaceDeal(GetPlayer.Self)`
- 提和：`War.ProposePeaceDeal(GetPlayer.Self)`（测试局里英国对尼德兰提白和，30 天答复期，对方接受开关 `War.ToggleAcceptPeace` 正常）
- **`War.SetWhitePeace` 在测试局里收下但没生成和约**；目前可靠的是 `ProposePeaceDeal`（白和也是它）
- 海军任务：`MilitaryFormation.CreateNavalMission(NavalMissionType.AccessSelf)`，任务类型来自
  `MilitaryFormation.GetPotentialMissionsTypes`；移除用 `MilitaryFormation.RemoveNavalMission`
- 默认造舰舰队：`AccessMetaPlayer...SetDefaultConstructionFleet(MilitaryFormation.Self)`，必须走非 const 玩家
- 成立国家：`CountryFormation.FormCountry(GetPlayer)`（新格拉纳达 → 大哥伦比亚，tag CLM → GCO）

### 公司 / 条约 / 权力集团

- 公司特许状：`Company.ToggleCharter(CompanyCharterType.Self)`（东印度公司「贸易权」）
- 退出条约：`Treaty.WithdrawFromTreaty`
- 权力集团踢人：`PowerBloc.Kick(Country.Self)`；测试局里大英帝国成员几乎都是附属，游戏拒绝
  「附属不能加入与宗主国不同的集团」，需要另建一个非附属成员的集团来验证

## 还没接的 8 条

### 1. 界面选择层（0 条，全部已接）

`Global.*Selected*`、`Global.MergeSelectedFormations`、`Global.SetStrategicObjectiveForSelectedFormations`、
`State.GetStationSelectedFormationsCommand`、`MobilizationOption.ToggleForSelected` 都已接：
有单编队等价命令的直接用单编队；没有的走 `Coverage.selected_action`（没有 UI 选择时返回「没有选中的编队」）。

`MilitaryFormation.Select` / `ToggleSelected` / `FormationPanel.SelectFormation` 是 UI 层函数：
数据系统调用后 `GetSelectedFormationsList` / `GetNumSelectedArmies` 都不变。测试过：
直接调用、先打开军事面板、路径加 `.Self`，均无效；已经找到并调用了真实的 `CMilitaryFormationPanel`
对象，`FormationPanel.SelectFormation` 只改面板自己的 `GetSelectedFormations`，不改全局选择。

### 2. 海域（2 条）

`SeaNodeMovementMarker.AddSeaRegionToSelectedFleetMissions` /
`AssignSelectedFleetsToNewMissionInRegion`：要一个真实的海域（`Province`）+ 选中的舰队。
单舰队的海军任务已经打通（`MilitaryFormation.CreateNavalMission`），但这两个命令是「把海域加到
**选中舰队**的任务里」，选择层和海域对象都还差一步。

海峡 10 条已经接到 `Coverage.strait_action`（○）：命令只在玩家**完全控制**海峡时可用。
测试局里把直布罗陀另一侧的州用控制台 `own STATE_AL_RIF` 划给英国后，`IsFullController` 仍为 0
（海峡还要求海上/军事控制），所以 10 条都只能到 ○。

### 3. 纯窗口对象（5 条）

已打通：4 个改名弹窗、`AddWarGoalPanel.AddWarGoal`、`WarGoalDraft.AddWarGoal`、
`MilitaryFormationBorrowSetting.GetBorrowingCommand`、君主随机 / 任命（2 条）。
已接（○）：`SwayCountryPanel.CreateSway`、`TransferFormationPopup.Confirm`、
`PowerBlocFormation.Confirm`、`ShipDesignerPopup.CreateTemplate/EditTemplate`、
`MilitaryFormationWrapped.EmbarkFormation` / `TransportPlannerPopup.*`（伪造包装，见 `Coverage.embark_formation`）。

| 命令 | 原因 |
|---|---|
| `WarGoalDraft.AddTreatyWarGoal` | 还要 `ArticleDraft`（条约条款草稿） |
| `InvasionPlannerPopup.StartInvasion` | 要规划器里的选中陆军 / 舰队（且要先开战） |
| `PowerBlocPrincipleSelectionWindow.SubmitPrincipleSelection` | 要原则选择窗口的选中项 |
| `ReleaseCountryWindow.ReleaseCountry` | 要 `CountryCreation` 草稿 |
| `TreatyDraft.SendProposal` | **读 `GetPotentialOffers` 会触发游戏访问违例**，测试时崩了一次；暂不继续 |

另：`ShipDesignerPopup.*` 本机 `HasDlcFeature('ship_designer')=0`，命令有效但游戏不落地。

### 窗口对象定位方法（已跑通）

1. **PopupManager 弹窗**：`eval_raw("PopupManager.AccessSelf")` 拿管理器指针 → 打开弹窗前读 0x800
   字节 → 打开后再读 → 差异里的新指针就是弹窗对象；
2. **信息面板**（AddWarGoalPanel / SwayCountryPanel / PowerBlocFormation…）：这些类有 RTTI，
   用 `. ? AVC类名@@` 找到 vtable（1.13.11 的 RVA 记在 `Coverage._VTABLES`），再扫描内存里
   `[对象+0] == vtable` 的地址（`Coverage._scan_vtable`）；
3. **改名弹窗的名字**是 `std::string`：对象 +0x90 是缓冲区/指针，+0xa0 是长度，+0xa8 是容量；
   写新名字后调 `Confirm`；
4. 调用命令时路径用 **`=@十六进制指针`**（桥接层新支持），把真实窗口对象当上下文；
5. 确认命令前先读 `IsValid(...)`，执行后读目标字段（公司/编队/州名、战争目标列表）。

### 4. 开局选君主（2 条，已打通）

多人大厅/开局用的 `PopupManager.ShowRulerSelectionPopup(Country.Self)` 在正常游戏里也能开：
`RandomizeRulersOffer` 换候选人（候选人名单实际变化），`SetRulerCommand(Character.Self)` 实际换君主
（道光 → 耆英）。对应 `Coverage.randomize_ruler` / `Coverage.set_ruler`。

### 5. 数据系统不支持的（1 条）

- `ScriptedGui.je_meiji_restoration_japanese_emperor_sgui`：`GetScriptedGui('…')` 不是数据系统函数，
  `IsValid` 与直接执行都失败。需要找到剧本按钮背后真正的效果命令。

## 怎么用

```python
from agent.bridge import Bridge
from agent.coverage import Coverage

a = Coverage(Bridge())
print(a.formations())                 # 陆军编队
print(a.ships())                      # 全部舰船
print(a.ship_constructions())         # 造船队列
print(a.naval_missions(0))            # 第 0 个舰队的可用海军任务
print(a.formation_action(0, "Mobilize"))
print(a.select_supply_priority(0, "high"))
```

MCP 里用 `act(kind="formation_action", params={"index":0,"cmd":"Mobilize"})` 一类调用；
`ACT_PARAMS` 里有全部参数说明。

## 下一步

1. 逆向 UI 选择管理器 / `FormationPanel` 单例，打通 3 条选择类与前线 / 指挥部的全局选择语义；
2. 找海峡注册表，打通 10 条海峡命令；
3. 给 21 条窗口命令逐个做伪造对象（优先级：WarGoalDraft → SwayOffer → TransferFormation → 其余）；
4. 用测试局把 ○ 的 75 条逐条变成 ✓（造可升级单位、造反舰、造征兵中心、非附属成员的权力集团）。
