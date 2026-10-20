# V3Bridge 逆向记录（1.13.11）

## 控制台
- `Console::Execute` 由字符串 `"Running console command: {}"` 定位，其后紧跟
  `call CommandManager::Get; lea r8,[tokens]; lea rdx,[result]; mov rcx,rax; call CommandManager::Execute`。
- `CommandManager::Execute` 是唯一引用 `"Unknown command"` 的函数。
- 参数：`Tokens = {std::string* data; int cap; int size; Alloc*}`，`Result = {bool ok; std::string text@+8}`。
- 控制台没有 save / pause / speed 命令（`help` 全表 4466 条）。

## 主线程
- 子类化主窗口 WndProc，HTTP 线程 `SendMessageTimeout` 投递；实测与游戏主线程同一线程。
- 超时后消息不会撤回，Job 必须放堆上。

## 数据系统（界面表达式）
- 读：`BuildLocData(03a85270)` + `FetchLocalized(03a85df0)`，文本 `"[...]"` → 字符串。
- 执行：`CreateStatement(03a7b010, flag=1)` → `Resolve(03a79b80)` → `CallVoid(03a797b0)`，
  即界面 onclick 的路径。`TimeKeeper.TogglePause` 已验证生效。
- **TODO**：上述地址目前写死在 `datasys.cpp`，需改成特征码定位
  （锚点："FetchData failed for '{}'"、"No function for call '{}'"、"Failed parsing statement for '{}'"）。
- `GetPlayer` 取不到有效国家，用 `GetMetaPlayer.GetPlayedOrObservedCountry`。
- 日期：`[TimeKeeper.GetCurrentDate.GetString]` → `1月 7, 1836`；`Date.Format(...)` 会访问违例，别用。
- `TimeKeeper.SetGameSpeed('(int32)4')` 访问违例（参数构造方式不对），待查。

## 存档
- 没有可直接调用的存档入口（`PauseMenu.Save` 只打开窗口，`SaveGameWindow.Save` 需要窗口上下文）。
- 退路：用户目录 `pdx_settings.json` 的 `game.autosave`（never/monthly/quarteryear/halfyear/yearly/five_year）。

## 开发接口
`/trace?rva=&hits=&ms=`（硬件断点抓栈）、`/mem?addr=&len=`、`/call?rva=&a1..a4=`。
