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

前置条件统一用 `IsValid(命令)`，原因用 `GetDesc(命令)`（界面按钮的灰显与提示就是这两个）。

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
