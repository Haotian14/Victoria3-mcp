# Victoria3-mcp

让程序玩《维多利亚 3》(Victoria 3)。思路与 [sts2-mcp](https://github.com/Haotian14/sts2-mcp)
一致：**策略写在代码里**（`src/agent/strategy/`），模型通过 MCP 调用，不靠把攻略塞进上下文。

**设计原则：不修改游戏文件夹的任何一个字节。**

## 与 sts2-mcp 的差异

sts2 是 .NET 游戏，CoreCLR Profiler 注入后靠反射就能读写所有对象。维多利亚 3 是
Paradox 的 C++ 引擎（Clausewitz / Jomini），没有符号，直接读内存对象需要大量逆向且
每次更新都会失效。所以分两阶段：

| 阶段 | 内容 | 状态 |
|---|---|---|
| 一：只读 | 游戏定义抽取、存档解析、经济策略；AI 能看懂局面、给出该做什么 | 进行中 |
| 二：动作 | 注入原生桥接 DLL，在 `127.0.0.1` 暴露与 sts2 同形的 `/state`、`/action/*` | 未开始 |

## 架构

```
Claude Code ──MCP──> agent (Python)                    第二阶段：
                      strategy/ 决策                    V3Bridge.dll（游戏进程内，C++）
                      data/     静态数据（游戏定义）  ──HTTP──>  127.0.0.1
                      save.py   读文本存档
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
| `rank_buildings(techs?, laws?, prices?)` | 可建造建筑按每点建造力的每周增加值排序 |
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
