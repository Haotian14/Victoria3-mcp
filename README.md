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
逆向细节与踩坑见 [docs/bridge.md](docs/bridge.md)。玩家能做的全部操作（界面按钮背后的游戏命令）及打通进度见 [docs/actions.md](docs/actions.md)。

| 里程碑 | 内容 | 状态 |
|---|---|---|
| 1 指令通道 | V3Bridge.dll 注入，控制台命令、数据系统读取与执行，特征码定位 | ✓ |
| 2 时间与存档 | 暂停、调速、推进到指定日期；每月自动存档 | ✓ |
| 3 快速读状态 | `observe.py` 经桥接层 1.5 秒读全局面；存档解析作兜底 | ✓ |
| 4 动作 API | 税率、研究、法律、改组政府、建造、生产方式，执行前后各读一次确认 | ✓ |
| 5 策略层 | 建造、生产方式、研究、法律、税率、事件、机构、州法令，规则在 `strategy/`、参数在 `data/strategy.json`（含国家档案 `country_profiles`） | ✓ |
| 6 runner 与 MCP | 每月决策一次；推进时间时每秒检查事件；`play` / `step` / `advise`；每局写 `logs/runs.jsonl` | ✓ |
| 7 自测 | 大清与普鲁士各跑十年：GDP 分别比不干预的基线高 5% / 7%（v4），过程见 docs/strategy.md | ✓（持续改进） |
| 8 玩家操作覆盖 | 从界面抽出的 266 条玩家命令：172 条已在游戏里跑通；其余 86 条已接且逐条实测受限，8 条未接；见 docs/coverage.md / coverage-test.md | ✓（进行中） |

## 架构

```
Claude Code ──MCP──> agent (Python)                      V3Bridge.dll（游戏进程内，C++）
                      observe.py  实时局面  ──HTTP──>      127.0.0.1:8766
                      actions.py  玩家动作                  ├ /console    控制台命令
                      game.py     启动 / 时间 / 存档        ├ /data/read  界面表达式求值
                      strategy/   决策                      ├ /data/exec  界面命令（onclick）
                      state.py    解析存档（兜底）          └ /data/list  界面列表逐项求值
```

## 策略从哪来

全部写在 `src/agent/strategy/`，参数在 `src/agent/data/strategy.json`，细节与来源见 [docs/strategy.md](docs/strategy.md)。

| 模块 | 每月做什么 |
|---|---|
| `construction.py` | 队列不够长或建造力没用满时补项目：先建造部门（木材/布料贵时先不扩），按各州征税能力缺口补行政机构，按攻略铺大学（大清 30 级），其余按「每点建造力的周利润」排序（市场价、当地工资率、已解锁的生产方式），扣掉缺劳动力、未并入、基础设施超用、供过于求的州 |
| `production.py` | 已建成的建筑每组挑「增加值 − 工资」最高的已解锁生产方式；差距不到 10% 不换；投入在本国无人卖的方式不选；大学单独按 pm_order 切哲学系 / 分析哲学系 |
| `research.py` | 按优先表推进，缺前置先研究前置；表走完按时代补位；国家档案（`country_profiles`）可覆盖优先表并设科技黑名单（大清：时代 5 陷阱不研究）；当前研究还在跑且队列空时，把下 1–2 项排进研究队列，避免空窗 |
| `politics.py` | 按游戏预计的通过率推路线上的法律（同一时间一条，低于阈值不推）；政府规模按法律动态限（独裁 2、寡头 3），超限先移除最小、非统治者、非乡村民众的集团；只差支持者时拉支持它的在野集团入阁 |
| `budget.py` | 只调税级：赤字且国库撑不过 30 周就加税，国库近储备上限且结余大就减税；国家档案可设税级下限 |
| `events.py` | 答所有待处理事件（以前从不调用，游戏按默认选项自动答）：鸦片危机默认让步避免开战，立法检查点优先推进，其余按效果关键词打分 |
| `institutions.py` | 按国家档案投资机构（大清：教育 1 级、卫生系统 1 级；机构基础上限就是 1，靠科技/法律提高）；税收浪费 >5% 或结余为负时先不加机构负担 |
| `decrees.py` | 按国家档案颁布州法令（大清：闹饥荒州「紧急救济」，人口大州「促进社会流动」，基础设施超用州「道路养护」） |
| `diplomacy.py` | 每月对俄 / 法 / 普改善关系（持续协定已生效就不再点）；自动回复提议：防御同盟 / 保障独立 / 贸易协定接受，要求 / 割让 / 赔款 / 投资权 / 治外法权 / 拉拢拒绝 |
| `subsidies.py` | 补贴亏损工业，但总额封顶收入的 3%；超额先砍非战略建筑中补贴金额最大的（工具 / 造纸 / 军工保护）；盈利后取消补贴 |
| `consumption.py` | 奢侈品消费税：茶 → 酒 → 鸦片 → 烟草 → 糖 → 瓷器，一次一项，权威力留 100 缓冲；不碰谷物 / 布料等民生品 |
| `trade.py` | 读每个商品当前的进出口档位，只发必要变更；缺货进口零关税、严重缺货出口高关税、过剩进口高关税；每次尝试锁 4 个月（游戏冷却 3 个月 + 7 天）；贸易中心每月扩 1 级 |
| `privatization.py` | 只对「有私有化资格、开关未开、实际现金流为正」的工业建筑打开私有化开关；`CanBePrivatized` 只是开关状态，不是资格 |
| `expansion.py` | 按人口并入未合并州（同时最多 2 个，税收浪费 >12% 暂停）；未合并州吃 −25% 基础设施等一整套惩罚 |

## 数据从哪来

| 来源 | 产物 | 用在哪 |
|---|---|---|
| 桥接层（界面表达式） | 实时局面：国库、收支、GDP、市场价、各州人口与建筑、法律、科技 | 每月决策 |
| `game/common/` 脚本定义 | `data/*.json`：商品基准价、建筑、生产方式（投入 / 产出 / 雇佣）、科技与前置、法律 | 建筑经济账、科技与法律规划 |
| `game/localization/` | 中英文名 | 界面名字 → 游戏 id |
| 存档（`*.v3`，文本格式） | 完整局面 | 兜底、核对（解析约 20 秒） |

刷新静态数据（游戏更新后）：`python tools/extract_gamedata.py`；刷新玩家操作清单：`python tools/extract_actions.py`

## 环境要求

| 依赖 | 版本 |
|---|---|
| Victoria 3 | 1.13.11（Steam appid `529340`），Steam 客户端在运行 |
| VS Build Tools + C++ 工具集 | 编译桥接层 |
| Python | 3.12+ |

## 构建与运行

```powershell
.\src\V3Bridge\build.ps1                       # 编译 bin\V3Bridge.dll
python -m pip install -r src\agent\requirements.txt
.\scripts\launch.ps1                            # 不经启动器开游戏（-debug_mode）、注入、等桥接层就绪
```

`launch.ps1` 常用参数：`-Save <存档名>` 载入指定存档、`-Restart` 先关掉正在运行的游戏、
`-Attach` 只给已运行的游戏注入、`-NoNotifications` 不弹窗不自动暂停。

### 开始玩

命令行：

```powershell
python scripts/play.py --months 12                                      # 接着当前局面玩一年
python scripts/play.py --save v3mcp_start_1836 --months 120             # 重开 1836，玩十年
python scripts/play.py --save v3mcp_start_1836 --tag PRU --months 120   # 换成普鲁士
python scripts/play.py --save v3mcp_start_1836 --baseline --months 120  # 对照：不做任何动作
python scripts/play.py --advise                                         # 只看本月计划
python scripts/check_clock.py                                           # 时间与存档的验收
```

`v3mcp_start_1836.v3` 是放在存档目录里的 1836.1.1 开局存档（大清）；换国家用控制台 `tag`。
每局在 `logs/runs.jsonl` 追加一行：逐月的 GDP、国库、结余、建造力、生活水平、识字率、人口与动作统计。

## MCP 工具

仓库根目录的 `.mcp.json` 已注册 MCP server。

| 工具 | 说明 |
|---|---|
| `play(months, save?, tag?, baseline?)` | 自动玩若干个月，返回首尾指标、动作统计与最后 40 条日志 |
| `step()` / `advise()` | 走一个月的决策 / 只看计划不执行 |
| `get_state()` / `query(text)` | 实时局面 / 求任意界面表达式 |
| `act(kind, ...)` | 手动下发一个动作：`set_tax` `research` `enact_law` `build` `set_pm` |
| `launch_game(save?, restart?)` / `health()` | 启动游戏并注入 / 桥接层状态 |
| `search` `lookup` `rank_buildings` `building_economics` | 查游戏定义、算建筑经济账 |
| `country_state` `save_summary` | 解析存档（兜底，慢） |

测试：`python -m pytest tests`（不需要游戏）

## 桥接层接口

```
GET  /health                       存活状态与定位到的游戏函数
POST /console?cmd=                 控制台命令
POST /data/read?text=              界面表达式文本求值："[GetMetaPlayer.GetPlayedOrObservedCountry.GetGDP|2]"
POST /data/exec?stmt=              执行界面命令："Execute(Building.QueueConstruction)"
POST /data/list?list=&fields=      界面列表逐项求值（fields 以 \x1f 分隔）
     &p0=&i0=&p1=&i1=...           上下文路径：逐层取列表项（州 → 建筑 → 生产方式组 → 生产方式）
POST /gov/reform?list=&igs=0,1,3   改组政府：igs 是改组后全部在朝集团在 list 里的下标
```

游戏侧失败是 HTTP 200 + `ok:false`（附游戏给的原因）。开发用的 `/trace`、`/mem`、`/call`、`/data/eval` 见 docs/bridge.md。

## 配置

| 变量 | 默认 | 说明 |
|---|---|---|
| `V3MCP_GAME_DIR` | 从 Steam 库自动找 | 游戏安装目录 |
| `V3MCP_USER_DIR` | `Documents\Paradox Interactive\Victoria 3` | 存档、日志所在目录 |
| `V3MCP_PORT` | `8766` | 桥接层端口（launch.ps1 传给游戏进程） |
| `V3MCP_URL` | `http://127.0.0.1:8766` | Python 侧的桥接层地址 |
| `V3MCP_BRIDGE_LOG` | `logs\bridge.log` | 桥接层日志 |

## 目录结构

```
src/V3Bridge/        桥接层 (C++)：注入后在主线程执行控制台命令与界面表达式
src/agent/           Python：桥接层客户端、实时局面、动作、runner、MCP 入口、存档解析
src/agent/strategy/  全部决策逻辑
src/agent/data/      静态数据（tools/ 生成）与策略参数（strategy.json，手写）
scripts/             启动、游玩、验收脚本
tools/               数据抽取脚本
tests/               单测（构造的数据，不需要游戏）
docs/                逆向记录（bridge.md）、策略说明（strategy.md）、玩家操作清单（actions.md）、
                     覆盖进度与缺口（coverage.md）、研究进度与 16 个方向（research-progress.md）、
                     下一会话交接与 prompt（next-session.md）
```

## 边界

- **仅用于单机游玩。** 不支持、不用于多人与铁人模式（游戏在这两种模式下也禁用控制台）。
- 不修改游戏目录；改的只有用户目录里的 `pdx_settings.json`（自动存档频率，游戏未运行时）。
- 游戏更新可能让特征码失效（`/health` 的 `error` 会说明哪一步没找到）或让 `data/` 过期 —— 重新跑 `tools/`。
