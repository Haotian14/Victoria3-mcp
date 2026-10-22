# 下一会话交接（2026-10-23）

## 一句话状态

16 份调研报告已全部读完并整合；1836 新档 10 年重跑完成，**经济大幅超过基线，但政治/承认路线卡住**。下一会话先解决“实业家养不起来 + 法律卡死 + 科技顺序”三个瓶颈。

## 先读什么

1. 本文件。
2. [research-progress.md](research-progress.md)：16 个方向的结论、已落地操作、10 年重跑数据与瓶颈。
3. [strategy.md](strategy.md)：策略模块说明；[README.md](../README.md)：运行方式与动作 API。

## 代码与环境

- 仓库：`C:\Users\Administrator\Desktop\Victoria3-mcp`
- 游戏：Victoria 3 **1.13.11**；桥接层 `127.0.0.1:8766`
- 测试：`python -m pytest tests -q`（当前 **75 passed**，不需要游戏）
- 新档重跑：`python scripts/play.py --save v3mcp_start_1836 --months 120`
- 当前游戏时间：**1846.1.1**（10 年重跑结束，已暂停）
- 最近提交：`9ebd313`（已推送）
- 用户偏好：中文、新手、要看到具体数字；**提交/推送只在用户明确要求时做，且不要加 Claude 署名**。

## 已经完成的（不要重复调研）

- 16/16 方向已读并整合，核心落地：贸易七档/冷却、消费税、补贴封顶、合法性护栏、私有化语义、工资除数、实际利润、队列硬停/优先建造、事件硬编码、并入未合并州、PM 优先扫描、饥荒救济、日志按钮白名单、外交方向守卫。
- 1836→1846 对比基线：GDP **116.5M vs 100.1M**、建造力 **190 vs 22**、识字率 **25% vs 14%**、SoL **6.62 vs 6.45**。
- 10 年只通过 **1 条法律**；寡头制/重商主义支持率 **0%**；实业家 **0.3%**（边缘化）。
- **建造力卡 190 已修**：预算份额阈值 0.7、允许 ≤3% 收入小赤字、国库 >26 周开支时赤字下也可扩建；实测 190→198（一个月），目标 100 级/210 建造力。

## 下一会话要做的三件事（按顺序）

### 1. 养实业家：金融区 + 公司（最高优先）

- 现状：`production.financial_candidates()` 只保证金融区用私人 PM，**没有建/扩金融区**；新档金融区等级低且 `can_queue=False`。
- 做：
  - 查哪些州金融区 `can_queue=True`，能扩就扩（目标 5–10 级/重点州）；
  - `corporate_charters` 研究后，查 `GetAvailableCompanies`/`GetMaxNumCompanies`，按“同州 5 级”创建资本家类公司（纺织/纸张/钢优先）；
  - 目标实业家 clout **≥5%（最好 6–7%）**，再拉入政府。
- 验证：`actions.companies()` / `actions.company(key)`；实业家 clout 与政府组成。

### 2. 法律卡死兜底

- 现状：寡头制 0% 支持，独裁上限 2 加不了支持者；农本主义 16% 被 `min_pass=0.35` 跳过；结果 10 年 1 条法。
- 做：在 `politics.py` 加“连续 24 个月没有法律可推”兜底——选通过率 ≥0.15 的路线法尝试；优先农本主义（解锁人均税），并记录失败锁 2 年风险。
- 验证：法律是否开始推进；不要为了兜底硬推 0% 的法。

### 3. 科技重排

- 现状：10 年 31 项，`colonization` / `railways` / `mutual_funds` 都没到；结束时还在 `corporate_charters`。
- 做：`colonization` 提到前 5–6 项（承认硬门槛）；`corporate_charters`/`mutual_funds` 提前；`romanticism` 后放。
- 验证：1846 前至少研究到 `colonization`；确认承认 JE 是否激活（还需废广州）。

## 复测与验收

1. `python -m pytest tests -q` 全绿。
2. 跑 `--save v3mcp_start_1836 --months 120`，对比本文件/ research-progress 的基线数字。
3. 重点看：法律数、寡头制/重商主义是否通过、承认 JE、实业家 clout、GDP/SoL/识字率。
4. 结果写回 `docs/research-progress.md`；用户要求时才 commit/push。

## 已知限制（不要当成新 bug）

- `building_railway` 不在快照建筑列表，铁路建造尚未接线（只有队列优先级）。
- 权力集团需承认后 rank ≥6 才能领导；当前未承认。
- 军事只接了军饷姿态，完整动员/登陆/白和自动化未做。
- 日志/决议只做鸦片白名单；其他按钮不自动按。
