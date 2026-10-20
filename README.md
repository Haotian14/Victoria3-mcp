# Victoria3-mcp

让程序玩《维多利亚 3》(Victoria 3)。思路与 [sts2-mcp](https://github.com/Haotian14/sts2-mcp)
一致：**策略写在代码里**（`src/agent/strategy/`），模型通过 MCP 调用，不靠把攻略塞进上下文。

**设计原则：不修改游戏文件夹的任何一个字节。**

## 怎么接上游戏

sts2 是 .NET 游戏，注入后靠反射就能读写对象；维多利亚 3 是 Paradox 的 C++ 引擎（Jomini），没有符号。
这里不去啃内存里的对象布局，而是借用游戏**界面自己用的数据系统**：

- 读：界面文本里的 `[GetMetaPlayer.GetPlayedOrObservedCountry.GetGDP]` 这类表达式，桥接层直接求值；
- 写：界面按钮 `onclick = "[Execute(Law.StartEnacting)]"` 背后的命令，桥接层用同一条路径执行。

所以动作与玩家点击完全等价（法律走推行流程、建造进队列、研究进研究槽），也不用截图或模拟按键。
逆向细节与踩坑见 [docs/bridge.md](docs/bridge.md)。

| 里程碑 | 内容 | 状态 |
|---|---|---|
| 1 指令通道 | V3Bridge.dll 注入，控制台命令、数据系统读取与执行，特征码定位 | ✓ |
| 2 时间与存档 | 暂停、调速、推进到指定日期；每月自动存档 | ✓ |
| 3 快速读状态 | `observe.py` 经桥接层 1.5 秒读全局面；存档解析作兜底 | ✓ |
| 4 动作 API | 税率、研究、法律、建造、生产方式，执行前后各读一次确认 | ✓ |
| 5 策略层 | — | 进行中 |

## 架构

```
Claude Code ──MCP──> agent (Python)                      V3Bridge.dll（游戏进程内，C++）
                      observe.py  实时局面  ──HTTP──>      127.0.0.1:8766
                      actions.py  玩家动作                  ├ /console    控制台命令
                      game.py     启动 / 时间 / 存档        ├ /data/read  界面表达式求值
                      strategy/   决策                      ├ /data/exec  界面命令（onclick）
                      state.py    解析存档（兜底）          └ /data/list  界面列表逐项求值
```

## 数据从哪来

| 来源 | 产物 | 用在哪 |
|---|---|---|
| `game/common/` 脚本定义 | `data/*.json`：商品基准价、建筑、生产方式（投入 / 产出 / 雇佣）、生产方式组、科技与前置、法律 | 建筑经济账、科技与法律规划 |
| `game/localization/` | 中英文名 | 查询与日志 |
| 存档（`*.v3`，文本格式） | 当前局面 | 市场价格、已研究科技、现行法律…… |

刷新数据（游戏更新后）：

```powershell
python tools/extract_gamedata.py
```

### 存档必须是文本格式

二进制存档的键是 token 号，对照表游戏不公开，本项目不解析。用 **`-debug_mode`** 启动游戏
（Steam → 右键游戏 → 属性 → 启动选项），非铁人模式下存档会写成文本。

## 环境要求

| 依赖 | 版本 |
|---|---|
| Victoria 3 | 1.13.11（Steam appid `529340`） |
| Python | 3.12+ |

```powershell
python -m pip install -r src\agent\requirements.txt
```

## MCP 工具

仓库根目录的 `.mcp.json` 已注册 MCP server。

| 工具 | 说明 |
|---|---|
| `search(text)` | 按 id 或中英文名查游戏定义 |
| `lookup(kind, id)` | 读一条定义 |
| `country_state(path?, states_limit?)` | 玩家国家局面：国库、收支、本地 / 世界价格、科技、法律、各州建筑 |
| `rank_buildings(from_save?, techs?, laws?, prices?)` | 可建造建筑按每点建造力的每周增加值排序；`from_save` 用存档里的本地价格、科技与法律 |
| `building_economics(building, ...)` | 单个建筑逐个生产方式组的账 |
| `save_summary(path?)` | 读存档，列出顶层结构 |

测试：`python -m pytest tests`

## 配置

| 变量 | 默认 | 说明 |
|---|---|---|
| `V3MCP_GAME_DIR` | 从 Steam 库自动找 | 游戏安装目录 |
| `V3MCP_USER_DIR` | `Documents\Paradox Interactive\Victoria 3` | 存档、日志所在目录 |

## 目录结构

```
src/agent/           Python：解析器、存档、静态数据、MCP 入口
src/agent/strategy/  全部决策逻辑
src/agent/data/      生成的静态数据（勿手改，用 tools/ 重新生成）
tools/               数据抽取脚本
tests/               单测（构造的数据，不需要游戏）
```

## 边界

- **仅用于单机游玩。** 不支持、不用于多人模式。
- 游戏更新可能让 `data/` 过期 —— 重新跑 `tools/` 即可。
