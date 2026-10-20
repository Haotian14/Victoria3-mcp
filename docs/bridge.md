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

前置条件统一用 `IsValid(命令)`，原因用 `GetDesc(命令)`（界面按钮的灰显与提示就是这两个）。

核实方式（`Actions` 里每个方法执行前后各读一次，写进 ActionResult 的 before / after）：
- 五档类（税、工资、补给舰）：当前档位的按钮是唯一 `IsValid` 为 0 的那个，界面也按它显示选中；
- 关税 / 补贴：`P.HasImportTariffsHigh(商品)` 等七个读数里为 1 的那个。**不要用** `Goods.GetStateImportTariffRate`
  之类的税率：暂停时它要等周结算才更新，命令明明生效了读数却不变；
- 消费税：`Goods.IsTaxed(P)`；暂停建造：`P.IsConstructionPaused` / `IsShipConstructionPaused`；公司：`P.GetNumCompanies`；
- 事件：选项效果五花八门，读一组「国家签名」（定时修正名单、国库、威望、合法性、在推行的法律）前后对比；
  没有即时效果的选项（如只设变量）照实报「已选，无可读的即时变化」。

条件类命令的测试准备（只在测试局里用，测完重新载入 v3mcp_start_1836）：
- 公司：大清开局没有可建立的公司，控制台 `ignore_company_requirements` 打开后再试，测完再输一次关掉；
- 事件：控制台 `event 事件名` 给玩家国家触发（`hungry_forties.2`、`east_indies.3` 选项效果是看得见的定时修正）；
- 控制台没有 `effect` 命令，测试留下的修正去不掉，只能重新载入存档。

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
