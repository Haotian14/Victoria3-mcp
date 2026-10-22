# V3Bridge 逆向与踩坑记录（1.13.11）

桥接层只做一件事：在游戏主线程里执行三类东西 —— 控制台命令、界面表达式求值、界面按钮背后的命令。
所有地址都在运行时按「字符串 → 交叉引用 → 调用序列特征码」定位，`/health` 的 `datasys` 字段列出定位结果。

## 注入与主线程

- `scripts/launch.ps1`：`SteamAppId=529340` 直接启动 `victoria3.exe -debug_mode`，3 秒后
  `CreateRemoteThread(LoadLibraryW)` 注入 `bin\V3Bridge.dll` 的**临时副本**（游戏运行时也能重编）。
- 主线程：子类化主窗口 WndProc，HTTP 线程 `SendMessageTimeout` 投递任务。实测窗口线程就是
  游戏主线程（`/trace` 抓到的界面求值都在这个线程上）。
- **`SendMessageTimeout` 超时后消息不会撤回**，主线程稍后仍会执行 —— 任务对象必须放堆上，超时就不释放。
- HTTP 每个连接一个线程（`/trace` 会阻塞等命中）；游戏侧任务都经 SendMessage 串行，不另加锁。

## 控制台

- `Console::Execute` 由 `"Running console command: {}"` 定位；其后紧跟
  `call CommandManager::Get; lea r8,[tokens]; lea rdx,[result]; mov rcx,rax; call CommandManager::Execute`。
- `CommandManager::Execute` 是唯一引用 `"Unknown command"` 的函数。
- 参数：`Tokens = {std::string* data; int cap; int size; Alloc*}`，`Result = {bool ok; std::string text@+8}`。
- 控制台**没有** save / pause / speed 命令（`help` 全表 4466 条）。时间与存档改走数据系统。

## 数据系统（界面表达式）

界面上 `text = "[GetPlayer.GetName]"`、`onclick = "[Execute(GetPlayer.SetTaxLevelHigh)]"` 用的同一套。
`dump_data_types` 控制台命令把全部类型与函数写到 `logs/data_types/`，查函数名以它为准。

| 用途 | 函数 | 定位 |
|---|---|---|
| 文本 → 段落 | `BuildLocData(StrView*, PdxArray* out, 0, 0, 0)` | `mov r9b,1; lea r8,[rbp-20h]; lea rdx,[rbp+140h]; mov rcx,[rip+工厂]; call CreateStatement` 所在函数 |
| 段落求值 → 字符串 | `FetchLocalized(Result*, PdxArray* loc, ctx, scratch)` | 唯一引用 `"FetchData failed for '{}'"` |
| 语句 | `CreateStatement(factory, StrView*, stmt, flag, 0)` | 同上调用序列 |
| 按值求值 | `Evaluate(stmt, ctx, scratch, CPdxAny*)` | FetchLocalized 里的调用 |
| 执行（onclick） | `Resolve(stmt, ctx, scratch, &target, &id)` + `CallVoid(stmt+0x18, &target, &argAny, scratch)` | Evaluate 里的 Resolve；`"No function for call"` 的两个引用者里 Evaluate 不用的那个 |

要点（每一条都踩过）：

- **CreateStatement 的 flag 必须为 1**（末端是函数）。flag=0 时末端当作 promote，`TogglePause` 会报 "Could not find promote"。
- **Evaluate 只能调有返回值的函数**，void 函数（`TogglePause`、`Execute(...)`）报 "No function for call"，要走 Resolve + CallVoid。
- **scratch 的 size 不能是 0**：回调按 `scratch.size` 新建临时实参数组再按下标取，size=0 时带参数的函数（`GetLawType('x')`）访问越界。
  界面按语句精确 resize，这里给固定 256。
- **语句的上下文需求表每项 8 字节**（stmt+0xb8，个数在 +0xc4），类型 id 在低 4 字节。按 4 字节读时单上下文碰巧对，多上下文全错。
- **部分函数断言必须在游戏状态访问作用域里**（`NGameState::GameStateAccess == Interface`）。用引擎自己的 RAII：
  `ctor(scope, 1 /*Interface*/, 0, reason)` / `dtor(scope)`，就在 `SetAccessToDestroyed` 后面紧挨着的两个函数。
- `GetPlayer` 在没有界面上下文时取到的国家是空的（GDP=0），用 `GetMetaPlayer.GetPlayedOrObservedCountry`；
  `Access*` 列表要求非 const，用 `AccessMetaPlayer.AccessPlayedOrObservedCountry`。
- `Date.Format(...)` 访问违例；日期用 `TimeKeeper.GetCurrentDate.GetString`（本地化文本，`3月 10, 1836`）。
- `TimeKeeper.SetGameSpeed('(int32)N')` 的 N 是 0..4（界面显示 1..5），给 5 无效。最高速约每秒 6 天。
- `TimeKeeper.IsPaused` 下一帧才更新，切换后要轮询。

### 列表（datamodel）与上下文

列表语句求值得到的 CPdxAny 里是数据模型 `{impl*, storage}`（类型指针低位为 1 时在堆上）。
`impl` 的虚表：`[0] Size(impl, storage)`、`[3] GetDataContext(impl, out[0x40], storage, i)`。
datacontext：`+0` 对象，`+0x28` 转换函数，`+0x30` 种类，`+0x38` 类型 id。转成上下文项 `{ptr, typeId, isConst}`：
种类 0/1 直接给指针（const / 非 const），其余调转换函数（游戏 035ee7c0 的等价实现）。

上下文路径：逐层取项、累积上下文，例如

```
p0 = AccessMetaPlayer.AccessPlayedOrObservedCountry.AccessStates      i0 = 0   → State
p1 = State.AccessBuildings                                            i1 = 2   → Building
p2 = Building.AccessProductionMethodGroups                            i2 = 0   → ProductionMethodGroup
p3 = ProductionMethodGroup.AccessBuildingProductionMethods(Building.Self) i3 = 1 → ProductionMethod
stmt = Execute(ProductionMethod.GetSwitch(Building.Self))
```

- 带上下文的文本只能有一个需要上下文的 `[..]`（同一段文本共用一个上下文数组）。
- `AccessBuildingProductionMethods(Building.AccessSelf)` 不行，要 `Building.Self`（与界面写法一致）。

### 已验证的玩家动作（全部是界面按钮背后的命令）

| 动作 | 语句 | 上下文 |
|---|---|---|
| 税率 | `Execute(P.SetTaxLevelMedium)` | — |
| 研究 | `Execute(GetTechnology('cotton_gin').Research(P.Self))` | — |
| 推行法律 | `Execute(Law.StartEnacting)` | 现行法律列表 → `Law.GetLawAlternatives` |
| 建造 / 扩建 | `Execute(Building.QueueConstruction)` | 州 → 五个建筑列表之一（含未建的潜在建筑） |
| 生产方式 | `Execute(ProductionMethod.GetSwitch(Building.Self))` | 州 → 建筑 → 方式组 → 方式 |
| 暂停 / 调速 | `TimeKeeper.TogglePause`、`TimeKeeper.SetGameSpeed('(int32)4')` | — |
| 改组政府 | `Execute(ReformGovernment.Confirm)` | 桥接层构造的拟议对象（`POST /gov/reform`，见下） |
| 政府 / 军队工资、补给舰建造档位 | `Execute(P.SetGovernmentWageLevelHigh)` 等 | — |
| 进出口关税与补贴 | `Execute(P.SetImportTariffsHigh(GetGoods('grain').Self))` 等 | — |
| 同上（预算面板写法） | `Execute(Goods.GetMarket.GetOwner.SetImportTariffsHigh(Goods.Self))` | `AccessFirstMarket.GetGoodsSortedByBalance` |
| 消费税开关 | `Execute(GetGoods('tea').ToggleTaxation(P))` | — |
| 暂停 / 恢复建造（含造船） | `Execute(P.PauseConstruction)` 等 | — |
| 创建 / 解散公司 | `Execute(P.CreateCompany(CompanyType.Self))` / `RemoveCompany(Company.GetCompanyType.Self)` | `GetAvailableCompanies` / `GetCompanies` |
| 事件选项 | `EventOption.Select`（界面上没有 Execute 包装） | 伪造的事件窗口 → `EventWindow.GetOptions`（`POST /data/fake`，见下） |
| 与利益集团谈判 | `Execute(PM.StartNegotiationWith(InterestGroup.Self))`（PM = 非 const 玩家） | `AccessAllInterestGroups` |
| 剧本按钮 | `Execute(ScriptedButton.ExecuteEffect)` | `AccessActiveJournalEntries` → `JournalEntry.GetScriptedButtons`（只含可见的） |
| 决议 | `Execute(Decision.TakeDecision(P))` | `PM.GetDecisions` |
| 机构投入 / 停止调整 | `Execute(Institution.StartChangingLevelTo(InstitutionInvestmentLevel.GetLevel))` / `StopSizeChange` | `AccessInstitutions` → `Institution.AccessInvestmentLevels` |
| 扶持 / 压制运动 | `Execute(PoliticalMovement.ToggleBolstering)` / `ToggleSuppression` | `AccessPoliticalMovements` |
| 取消推行法律 | `Execute(Law.StopEnacting)` | 现行法律 → `Law.GetLawAlternatives` 里 `IsBeingEnacted` 的那条 |
| 对附属国强加法律 | `Execute(Law.StartImposing)` | `PM.GetSubjects` → 附属国的四个法律列表 → `Law.GetLawAlternatives` |
| 废除修正案 | `Execute(Amendment.Repeal)` | 现行法律 → `Law.GetAllAmendments` |
| 建造队列上移 / 下移 / 置顶 / 置底 / 取消 | `Execute(ConstructionQueueElement.MoveUp)` 等 | `PM.AccessGovernmentConstructionQueue`（或 `AccessPrivateConstructionQueue`；界面用的分页列表依赖面板） |
| 建筑：补贴、自动扩建、私有化、国有化、缩减、取消建造、暂停建造部门产出、生产方式恢复默认 | `Execute(Building.ToggleSubsidies)`、`Building.NationalizeBuildingLevels('(int32)1')` 等 | 州 → `State.AccessBuildings` |
| 按类型恢复生产方式 | `Execute(Building.GetBuildingType.ResetProductionMethodsToStandard)`（界面同写法） | 同上 |
| 全部建造部门换方式 / 暂停 / 恢复 | `Execute(ChangeAllConstructionSpeed(ProductionMethod.Self))`、`PauseAllConstruction` | `AccessConstructionSpeeds`（全局） |
| 州法令 | `Execute(DecreeType.GetSetCommand(State.Self))` / `Decree.GetRemoveCommand` | 州 → `State.GetPotentialDecrees` / `State.AccessDecrees` |
| 并入 / 取消并入、暂停殖民、放弃殖民地 | `Execute(State.IncorporateState)` 等 | 州 |
| 殖民 | `Execute(GetStateRegion('STATE_X').Colonize)`（界面写 `State.GetStateRegion.Colonize`） | — |
| 研究队列 | `Execute(GetTechnology('x').ResearchWithUnlocks(P.Self))` / `AddToQueueWithUnlocks` / `RemoveFromQueue` | — |
| 动员 / 复员全部军队 | `Execute(P.MobilizeAllArmies)` / `DemobilizeAllArmies`（要在外交博弈或战争中） | — |
| 外交行动 | 伪造确认窗口后 `Execute(DiplomaticActionWindow.ExecuteAction)`（见下「外交」） | `=GetStateRegion('…').GetLargestStateOwner` → `Country.GetAvailableGeneralDiploActions` 等十个列表 |
| 发起外交博弈 | `Execute(GetDiplomaticPlayType('dp_humiliation').GetStartCommandCountry(P.Self, Country.Self))`（界面先弹确认窗，确认发的就是它） | `=…`（目标国） |
| 博弈表态 | `Execute(DiplomaticPlay.LeanTowardsTarget(P))` 等 | `PM.AccessActiveDiplomaticPlays` |
| 战争：坚持战争目标 / 提和 / 接受和约 | `Execute(WarGoal.ToggleIsPressedInPotentialPeaceDeal(P.Self))`、`War.ProposePeaceDeal(P.Self)`、`War.ToggleAcceptPeace(P.Self)` | `PM.AccessWars` → `War.GetAttackersWarGoals`（界面经 `WarPanel.GetWar`，命令本身在 War 上） |
| 退出条约 | `Execute(Treaty.WithdrawFromTreaty)` | `PM.GetInForceTreaties` |
| 发起针对州的博弈 | `Execute(GetDiplomaticPlayType('dp_conquer_state').GetStartCommandState(P, State.Self))` | `=…GetLargestStateOwner` → `Country.AccessStates`（按 `State.GetStateRegion.GetID` 找） |
| 将领：招募 / 晋升 / 编入 / 解除 / 下令 | `Execute(Character.GetRecruitCommandNoFormation)`、`GetRecruitCommand(MilitaryFormation.Self)`、`GetPromoteCommand`、`AssignToFormation(MilitaryFormation.Self)`、`UnassignFromFormation`、`SelectOrder(CommanderOrderType.Self)` | `PM.AccessGeneralsOffer` / `AccessGenerals`（海军 Admirals）、`PM.GetMilitaryFormationsArmy` / `Fleet`、`Character.AccessOrders` |
| 默认造舰舰队 | `Execute(PM.SetDefaultConstructionFleet(MilitaryFormation.Self))` / `ClearDefaultConstructionFleet` | `PM.GetMilitaryFormationsFleet` |
| 成立国家 | `Execute(CountryFormation.FormCountry(P))` | `PM.AccessFormableCountries` |
| 公司特许状 | `Execute(Company.ToggleCharter(CompanyCharterType.Self))`；要选目标的用 `Company.ToggleBuildingCharter(GetCompanyCharterType('industry_charter').Self, GetBuildingType('…').Self)` / `ToggleRegionCharter(…, GetStateRegion('…').Self)` | `PM.GetCompanies` → `GetCompanyCharterTypes` |

前置条件统一用 `IsValid(命令)`，原因用 `GetDesc(命令)`（界面按钮的灰显与提示就是这两个）。

核实方式（`Actions` 里每个方法执行前后各读一次，写进 ActionResult 的 before / after）：
- 五档类（税、工资、补给舰）：当前档位的按钮是唯一 `IsValid` 为 0 的那个，界面也按它显示选中；
- 关税 / 补贴：`P.HasImportTariffsHigh(商品)` 等七个读数里为 1 的那个。**不要用** `Goods.GetStateImportTariffRate`
  之类的税率：暂停时它要等周结算才更新，命令明明生效了读数却不变；
- 消费税：`Goods.IsTaxed(P)`；暂停建造：`P.IsConstructionPaused` / `IsShipConstructionPaused`；公司：`P.GetNumCompanies`；
- 事件：选项效果五花八门，读一组「国家签名」（定时修正名单、国库、威望、合法性、在推行的法律、是否在谈判）前后对比；
  没有即时效果的选项（如只设变量）照实报「已选，无可读的即时变化」。分类事件（立法、谈判）答完会立刻从
  `GetEventsByCategory` 里消失，谈判的 `IsNegotiating` 也立刻变 0；
- 剧本按钮：按钮的可见性跟着效果变（「禁止鸦片贸易」按下后换成「取消鸦片禁令」），连同国家签名一起对比；决议看国家签名；
- 机构：`Institution.GetTargetInvestmentLevel`（不在调整时读 0）、`IsChangingLevel`；运动：`IsBolstered` / `IsSuppressed`；
  取消立法：`P.IsEnactingLaw`；修正案：现行法律上的修正案名单；
- 强加法律：附属国要到之后的结算才开始推行，即时可读的是 12 个月的强加冷却——同一条命令的 `IsValid` 由 1 变 0；
- 建造队列：整条队列的（建筑, 州）顺序与预期的新顺序比；取消看队列长度；
- 建筑：`IsSubsidized` / `IsAutoExpanding` / `CanBePrivatized`（私有化开关就翻它）/ `GetNumLevelsCanBeNationalized` /
  `GetTotalLevels` / `GetExpansionLevelsInQueue` / `IsConstructionOutputPaused` / 各方式组现行生产方式。
  **州里的建筑列表按等级排序**：缩减、取消建造之后同一下标会换成别的建筑，核实时每次按建筑 key 重新找路径；
- 按类型恢复生产方式、全部建造部门换方式、殖民：作用范围大或要到结算才落地，看同一命令变为不可用
  （「所有生产方式都已调整为国家标准」「该生产方式已在所有建筑中激活」「我们在这里已经有殖民地」）；
- 殖民地下一次结算才作为州出现，用 `State.IsGrowingColony` 认（`IsBeingColonized` 不是它）；
- 法令：州的现行法令名单；并入：`IsIncorporated` + `IsIncorporating`（对正在并入的州「取消并入」是停下并入）；
- 特许状：公司的 `HasAny*CharterActive` / `Company.GetActiveCharters(类型)`；授予后几年内不能撤销（游戏规则，GetDesc 会说）；
- 研究：正在研究的科技 + 研究队列（`GetResearchQueueTop` / `Bottom`；科技没有 `GetKey`，按中文名对回 id）；
- 外交行动：`DiplomaticAction.IsActivePact`、能否再发、原因、`P.GetRelationsWith(Country.Self)`（驱逐外交官：关系 0 → -30）；
- 博弈：玩家参与的博弈名单；表态看 `IsInitiatorLeaning` / `IsTargetLeaning` / `IsOnTheFence` / `IsInitiatorOrBacker` /
  `IsTargetOrBacker`，中立后博弈从该国列表消失。退让（Yield）开场阶段不可用；转换阵营要到战争阶段；
- 战争：`WarGoal.IsPressedInPotentialPeaceDeal(P.Self)` / `IsPrimaryDemand`、`War.HasActivePeaceDeal`，结束后战争从列表消失；
- 将领：**列表按军衔排序**，晋升、编入后同一下标会换人，核实时按名字重新找；军衔 `GetRankName`，所属编队
  `GetMilitaryFormation` + `IsTravellingToFormation`（编入后要赶路），命令 `GetOrderType`；
- 默认造舰舰队：各舰队的 `MilitaryFormation.IsDefaultConstructionFleet`。**经只读的玩家路径（GetMetaPlayer…）执行
  `SetDefaultConstructionFleet`，游戏收下了却不生效，要用非 const 的 AccessMetaPlayer…**（税率之类不受影响）；
- 成立国家：玩家的 tag（`GetTagName`，新格拉纳达成立大哥伦比亚后 CLM → GCO）。

条件类命令的测试准备（只在测试局里用，测完重新载入 v3mcp_start_1836）：
- 公司：大清开局没有可建立的公司，控制台 `ignore_company_requirements` 打开后再试，测完再输一次关掉；
- 事件：控制台 `event 事件名` 给玩家国家触发（`hungry_forties.2`、`east_indies.3` 选项效果是看得见的定时修正）；
- 剧本按钮 / 决议：`add_journal_entry je_opium_obsession` 给大清加鸦片条目（按钮「禁止鸦片贸易」）；
  禁烟后 `invalidate_journal_entry je_opium_obsession`，决议「取消鸦片禁令」就出现；
- 机构、谈判、强加法律、修正案：大清开局没有可调的机构、附属国，`tag GBR` 换成英国测（英国推行普选制时
  小市民可谈判；附属国上加拿大可强加法律），修正案用 `tag SWE`（瑞典的普鲁士式教育可废除）；
- 经济：英国伦敦周边的建筑几乎每条命令都能用；建造队列先 `Building.QueueConstruction` 排几项；
  殖民用 `research quinine` 解锁纳马夸兰（`STATE_NAMAQUALAND`），殖民特许状用赫雷罗兰；
- 外交：英国对法国、普鲁士、奥地利、俄国的外交行动；对托斯卡纳 / 尼德兰发起羞辱博弈，对两西西里发起征服西西里；
  第三方表态 `tag SPA` / `tag FRA` / `tag SAR`；推进约 3 个月对尼德兰的博弈转为战争，英国提和后 `tag NET` 接受和约；
- 成立国家：`tag CLM` 后控制台 `annex VNZ`、`annex ECU`，再成立大哥伦比亚；
- 控制台没有 `effect` 命令，测试留下的修正去不掉，只能重新载入存档。

### 军事、舰船与选择（2026-10-22）

- **编队**：`PM.GetMilitaryFormationsArmy` / `GetMilitaryFormationsFleet`（已用于将领、编队命令）。
  编队里的单位：`MilitaryFormation.GetCombatUnitEntries`（每项是 `MilitaryFormationUnitEntry`，
  `GetUnitType` 是该类型的 `CombatUnitType`）；具体战斗单位在 `MilitaryFormationUnitEntry.GetCombatUnits`。
  单位组升级用 `MilitaryFormation.GetEligibleGroups`（项是 `CombatUnitGroup`）。
- **舰船**：`PM.GetShipList` 是玩家国家的 `ShipList`；`GetShips` / `GetShipTemplates` /
  `GetShipConstructions` 都是它的列表。某个舰队的舰船列表要写完整的
  `MilitaryFormation.GetShipList.GetShips` 加路径到编队；写成 `GetShipList.GetShips` 会报
  `Failed to find type 'GetShipList'`。
- **舰船选择**：`ShipList.GetActiveSelection` 只在**某个 ShipGroup 的编辑模式**里非空；
  先 `ShipList.ToggleEditMode(ShipGroup.Self)`（路径：ShipList + `GetShipGroups` 项），
  再用 `=AccessPlayer.GetShipList.GetActiveSelection.Self` 作为上下文。直接写
  `=AccessPlayer.GetShipList.GetActiveSelection` 会报 `Promote ... returned nullptr`。
  选择命令是 `ShipSelection.ToggleSelection(Ship.Self)`、`SelectFiltered`、`Retrofit`、`Decommission`、
  `ChangeTemplate(ShipTemplate.Self)`。
- **编队选择是 UI 层**：`MilitaryFormation.Select` / `ToggleSelected` 在数据系统里调用后，
  `GetSelectedFormationsList` / `GetNumSelectedArmies` 都不变；`FormationPanel.SelectFormation`
  只能从面板上下文拿到，没有全局 getter。所以 `Global.*Selected*`、`Front/Hq/Invasion` 的
  「对选中编队」命令暂时走不了；单编队版本（`MilitaryFormation.Mobilize` 等）已经接通。
- **海峡**：数据系统里只有 `StraitMarker.GetStrait` / `StraitPanel.GetStrait`，没有全局海峡列表；
  临时的 `StraitPanel` 也没有 getter。要把 `Strait.*` 接上，需要找运行时的海峡注册表。

### 外交（路径步「=表达式」、伪造确认窗口、伪造 TopFrontend）

- **按值取对象作上下文**：数据系统没有全部国家的列表，也没有按 tag 取国家的函数。`GetStateRegion('STATE_X')`
  是全局函数，`.GetLargestStateOwner` 就是该地区的国家，但它是只读（const）的，后面接 `GetAvailable…DiploActions`
  这种要求非 const 的列表时语句建不起来（error.log：`requires non const promote`）。桥接层的路径步支持
  `p0==表达式`：按值求出对象（CPdxAny 是 `{类型信息*, 对象*}`，const 与否只差类型信息），作为非 const 的通配上下文。
  tag → 地区 在 Python 里扫一遍全部地区的 `GetLargestStateOwner.GetTagName` 缓存起来；
- 有多个通配上下文时取最近加入的（伪造对象排在「=表达式」之后）；
- **外交行动**：国家面板按钮的 onclick 是 `DiplomaticAction.ExecuteWithConfirmation`（不经 Execute）。它（1.13.11 的
  `01fdea30`）看外交行动类型 +0x48 的「需要确认」位：不需要的直接组装命令发出（关系类），需要的（宿敌、驱逐外交官……）
  打开确认窗口 `DiplomaticActionWindow`，玩家点确认才发。**直接 `Execute(DiplomaticAction.ExecuteAction)` 游戏收下了
  却什么也不做**（改善关系执行后协定没有建立）。确认窗口构造函数 `021bd860`：+0xd8 / +0xdc 两国 id
  （外交行动对象 +0x10 / +0x14）、+0xe0 / +0xe4 选的州（-1）、+0xe8 = 1、+0xf0 外交行动类型指针（对象 +0x28）、
  +0xf8 义务、+0xfc = 2；`DiplomaticActionWindow.ExecuteAction`（`021caac0` → `021be590`）只读这几项组装
  `CExecuteDiplomaticActionCommand`。所以一律伪造确认窗口（spec 用 `cK@偏移` 从路径上的外交行动对象抄，
  `q` 类型读 8 字节指针）再 `Execute(DiplomaticActionWindow.ExecuteAction)`，需不需要确认的都对；
- **提议**（别国发来的条约、外交行动、要求、拉拢）挂在界面对象 `TopFrontend.AccessProposals` 上。它的回调先调
  `02361860` 清空 +0x30 的数组、再从游戏状态按本地玩家重建，所以伪造对象只要 +0x30 一个空数组（spec `0:30:a=0`）。
  接受 / 拒绝的命令与 popups.gui 的写法一致（`Proposal.GetTreaty.AcceptTreatyProposal` 等）。

### 事件（`POST /events`、`POST /data/fake`）

数据系统只有分类事件的列表（`GetEventsByCategory('enactment' / 'negotiation' / 'revolution')`），
大多数事件（弹窗、地图标记）没有列表可走；事件窗口 `EventWindow` 是界面对象，选项 `EventOption` 只挂在它上面。
静态分析（1.13.11 地址仅作记录，桥接层按 RTTI 与特征码定位）：
- `EventOption.Select` 的回调 `02100980`：选项对象是 `{窗口*, int 下标}`，调 `020ff9a0(窗口, 下标)`；
- `020ff9a0`：窗口 +0x128 是「已选」标记；`[窗口+0x88]+0x10` 是事件 id，经查找函数 `00e7a0c0` 取到事件对象
  （`CGenericEvent`，+0x08 是 id，高 8 位是代数），组装 `CSelectEventOptionCommand`
  （0x30 字节：+0x20 国家 id、+0x28 事件 id、+0x2c 选项下标），校验后 `call 00cd2d00(…, 0xE)` 发出；
- 查找函数开头 `mov rax,[rip+X]` 的 X 就是事件对象库：+0x20 槽数组（16 字节一槽，对象指针在 +8），+0x2c 槽数；
  桥接层的定位链：RTTI `.?AVCSelectEventOptionCommand@@` → 虚表 → 引用它且含 `mov edx,0Eh` 的函数 →
  其中 `add rcx,10h; call` 的目标 → 开头的 `mov rax,[rip+X]`；
- **数据系统里的 `Event` 不是事件对象，而是 +0x10 放事件 id 的句柄**（`Event.GetNumRemainingDays` 等回调都先
  `add rcx,10h` 再查库）。`/events` 遍历对象库，每个事件给一个这样的句柄作上下文去求 fields；
- `EventWindow.GetOptions`（`020ffba0`）现场按选项条件重建 +0x110 处的选项数组（`CPdxArray`，要带分配器），
  所以伪造窗口只要两样：+0x88 → 句柄（+0x10 = 事件 id），+0x110 = 空数组（spec 类型 `a`）。
  列出的就是窗口里显示的选项，选项对象里存的是**原始下标**（`east_indies.3` 第一项条件不满足，
  窗口第 0 项就是原始第 1 项）；
- **命令本身不检查选项条件**：直接按原始下标发命令，条件不满足的选项也会生效。所以一定要经
  `EventWindow.GetOptions` 的列表项去选，不要自己拼下标；
- **游戏不拒绝对同一事件的重复回答**：暂停时事件要到下一天才从库里移除，再选一次效果会再叠一次。
  `Actions` 记下本进程已回答的事件 id，不再重复；
- 伪造对象（`/data/fake`）是改组政府做法的通用版：`spec` 按「缓冲区:偏移:类型=值」填 4 块 0x1000 字节的缓冲区，
  0 号作为通配上下文；不引用路径项时先填再走路径，所以路径里的列表也能以伪造对象为上下文
  （`p0=EventWindow.GetOptions&i0=1` 再执行 `EventOption.Select`）。mode `x` 执行、`r` 求文本、`l` 列表逐项求值。

立法相关的读数（都在法律的可选项上，`Law.GetLawAlternatives` 之后）：
- `Law.GetCheckpointSuccessChance` / `AdvanceChance` / `StallChance` / `DebateChance`：对**还没开始推行**的法律
  也给预计值，已按当前政府、君主、运动算好；
- `InterestGroup.IsEndorsingLawEnactment(Law.Self)` / `IsOpposingLawEnactment(Law.Self)`：立法时谁支持、谁反对
  （再叠一层 `AccessAllInterestGroups` 的路径）。参数必须是 `Law.Self`，`Law.GetLawType.Self` 求值失败。
  **不要用 `GetApprovalValueIfEnacted`**：那是推行后的认可度，和立法立场不是一回事
  （大清乡村民众对佃农制认可度不变，却是支持者）。

### 改组政府（`POST /gov/reform?list=<利益集团列表>&igs=0,1,3`）

界面上的 `ReformGovernment`（`CReformGovernment`，没有虚表）挂在政治面板上：`PoliticsPanel.AccessReformGovernment`，
上下文类型是界面对象，从玩家国家走不到，`InformationPanelBar.OpenPanelTab` 之类也是界面上下文、构建语句就失败。
静态分析（capstone，1.13.11 地址仅作记录，桥接层不依赖）：
- RTTI `.?AVCReformGovernmentCommand@@` → 虚表 → 构造函数 `011f09f0(cmd, 国家 id, CPdxArray<CInterestGroup*>*)`；
- 唯一的界面调用方是 `ReformGovernment.Confirm` 的回调 `0228a140` → `02286390`：只读拟议对象的
  **+0x18 名单 data / +0x24 个数**（元素是利益集团对象指针，对象 +0x08 是侵入式引用计数、+0x10 是 id），
  玩家国家从全局取，make_shared 出命令后交回 CPdxAny，由外层 `Execute` 发出 —— 与推法律、建造同一条路；
- `GetPredictedLegitimacy` 读的是缓存字段 +0xf4，由加入 / 移出名单时的更新函数（`02284470`）算，不是现算。

所以桥接层构造一个只填名单的对象（名单元素直接用 `AccessAllInterestGroups` 列表项给出的对象指针），
作为上下文执行 `Execute(ReformGovernment.Confirm)`。上下文类型 id 用不着知道：`make_ctx` 支持一个
「顶替任何没配上的需求」的通配项。名单是**改组后的全部在朝集团**。

实测（1836.1.1 大清）：士大夫 → 士大夫 + 军队 + 乡村民众，合法性 100 → 82；可推法律从 3 条变成 10 条
（佃农制、农民产权、职业军队、国民警卫队……）。

坑：
- 第一次以为列表项是「句柄」、按 +0x08 读 id，结果三个集团读出来都是 7（那是引用计数），命令发出去政府没变；
  用 `/data/eval` 取君主所属集团的指针、`/mem` 看对象头才对上 +0x10。
- 规则（defines）：把集团**移出**政府会让它 25% 的支持者激进化（选举后 6 个月内免费，独裁制没有选举）；
  每多一个超出编制的集团合法性 −20。策略只加不减。

## 存档

- 没有可直接调用的「立即存档」：`PauseMenu.Save` 只是打开存档窗口，`SaveGameWindow.Save` 需要窗口自己的上下文。
- 改用游戏的自动存档：用户目录 `pdx_settings.json` 的 `game.autosave`
  （`never / monthly / quarteryear / halfyear / yearly / five_year`）。**游戏退出时会覆盖这个文件**，只在游戏未运行时改。
- 自动存档轮换 `autosave.v3`、`autosave_1.v3`…；文件头 `meta_data.game_date` 可直接读（`save.peek_meta`）。
- 存档里有以块为键的映射（移民目标：`{ culture=49 ... } = { num_to_migrate=432 }`），解析器按 `_pair` 保存。

## 收支与国库（已核实）

- 界面 `GetWeeklyIncome` / `GetWeeklyExpenses` = 存档 `budget.weekly_income` / `weekly_expenses` 各项之和（逐分对上）；
  `GetWeeklyBalance` = 两者之差。1836.3.1 大清：收入 282,782、支出 177,716、结余 +105,066/周。
- `GetGoldReserves` = 存档 `budget.money`，单位就是英镑（£5,166,346）。1.1 → 3.1 国库增加约 87.6 万，
  合每周约 10.3 万，与结余一致。

## 开发接口

`/trace?rva=&hits=&ms=`（硬件断点抓调用栈、寄存器与栈顶）、`/mem?addr=&len=`、`/call?rva=&a1..a4=`、
`/data/eval?stmt=&flag=`（原样返回 CPdxAny）。正常游玩用不到。
