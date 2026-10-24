# v6 攻略驱动改动清单（1836→1861，300 个月）

> 来源：上个会话（2026-10-24）转写的三个 B 站攻略
> - `logs/bili_baby_full.txt`（宝宝巴士新手全流程，UP：公鸟）
> - `logs/bili_adv1_20m.txt` / `logs/bili_adv2_20m.txt`（进阶攻略前 20 分钟，UP：空调）
>
> 本文件只做**攻略 → v5 参数 → v6 建议**的对齐，并记录实施状态。P0 是纯 `strategy.json` 改动，P1/P2 需要动 `src/agent/`。

## 0. 一句话结论

攻略的主线是：**开局压低政府/军队工资 + 只收服务税 → 建造部门/贸易中心/大学三件套 → 农奴制→佃农、传统主义→经济干预 → 公立学校 → 1850 年代铁路/水管锅炉/转炉 → 约 1861 钢框架 → 公司/天朝上国**。

v5 的偏差集中在五处：

1. **法律路线绕了农本主义、职业军队、贸易保护**，占掉立法槽；
2. **科技把钢框架排得太后**，且把攻略要用的 `chemical_bleaching`、`canneries` 拉黑了；
3. **贸易中心 60 级 / 大学 50 所 / 行政 80 级**与攻略的“10 级 / 创新上限 / 40 级”不一致；
4. **没有政府工资、外交信任/贸易特选、朝贡、脆弱的统一、战争模块**；
5. **公司只有“建”没有“换/删”**，攻略里纸张/建设公司都是过渡，后期要替换。

建议 v6 以 **300 个月（1836→1861）** 为验收窗口，180 个月承认战争作为二期目标，不再和经济发展抢同一轮。

---

## 1. 攻略时间线（从转写提取）

| 阶段 | 攻略动作 | 关键数值/条件 |
|---|---|---|
| 开局 1836 | 税级 Medium；消费税只收**服务**；政府/军队工资压到极低；删 5 个海防要塞 | 服务税不压食品/衣服/鸦片；低工资换建造资金 |
| 开局 1836 | 伐木：大部分软木，3 处硬木；硬木价格比软木高 50–60 | 为建造预留软木产能 |
| 开局 1836 | 建造部门先拉 **60 级**；贸易中心 10 级（广东）；兵营 5 级；大学每州 1 级 | 60 级 + 钢框架 ≈ 300 建造力 |
| 开局 1836 | 政府行政 10 级（江西）；6 个人口最大州开“促进社会流动” | 不追前期 69k 税收浪费；1670 万才回本 |
| 1836–1840 | 外交：给所有列强**贸易特选**（99 年也行）→ 才能改善关系；送金币、给 5 年义务换使馆/法律承诺 | 8 个列强；不要给投资权；不要给 15 年义务 |
| 1836–1840 | 收朝贡国（不丹/尼泊尔/缅甸/越南等），凑 10 个解锁“授权”栏；拿“附近研究”buff | 减少学校行政力、加科技速度 |
| 1836–1845 | 法律：农奴制→佃农；传统主义→经济干预；人均税制；公立学校 | 不要改农本主义（除非要跳自由放任） |
| 1840–1850 | 科技：证券交易所 → 殖民 → 经验主义 → 化学漂白 → 铁路 → 水管锅炉 → 转炉 → 机械工具 | 证券交易所的 +10% 早拿 |
| 1840–1850 | 大学补到创新上限：23 所吃满 100%，再补 3–5 所；超出部分 5:1 转科技扩散 | 不是固定 50 所 |
| 1850–1861 | 钢框架（约 1861）；切钢框架前先扩玻璃/钢/工具 | 玻璃会爆价；铁价会跌 |
| 1861+ | 公司：纸张（过渡）→ 统一建设联合体（过渡）→ 精密工具/钢/军工；三级公司 | 过渡公司后期删掉 |
| 1861+ | 受认可后成立“天朝上国”；天朝上国原则拿“普鲁士教育”（同化） | 提高同化速度 |
| 全程 | 脆弱的统一：开局 5 点，失败事件 −1；≤0 分裂。义和团失败会 −1；君主制改动要留 ≥2 点 | 不要主动借款/政变/内战 |
| 全程 | 陆军：合并编队、升将军；200 营 + 50 炮 + 50 征召打尼泊尔/缅甸；战时军饷 Medium | 将军忠诚 > −5，避免 −20% 土地税 |
| 后期 | 贸易中心人多时降回 1 级，把店主赶去工厂 | 防止几千万人卡在贸易中心 |
| 后期 | 生活水平冲刺：合作社/自由放任、妇女选举权、义务小学 | 目标 SoL 15 |

---

## 2. 与 v5 的逐项差异

| 项目 | v5 现状 | 攻略 | v6 建议 | 类型 |
|---|---|---|---|---|
| 税级 | `tax_floor=Medium`，但 `budget.min_tax=Low`，45–49 合法性会降 Low | 固定 Medium | `budget.min_tax=Medium` | P0 配置 |
| 消费税 | 茶/酒/鸦片/烟草/糖/瓷器，最多 2 项 | **只收服务税**；中期才收高档奢侈品 | 主序列改 `["services"]`，茶作兜底；`opium/tobacco/sugar/porcelain` 移出主序列 | P0 配置 |
| 政府工资 | 未接（runner 只设 Military） | 前期极低 | 前期 Low，1842 前/非战时/现金紧时启用；其余 Medium | P1 代码 |
| 军队工资 | 和平 Medium，战时 High | 攻略说也压低，但调研：Low −50% 训练 | **保持 Medium；战时 High** | 不改 |
| 补贴 | 收入 3% 封顶，每月 2 个 | 能不补就不补 | 封顶降到 1.5%，每月 1 个；只保工具/造纸/军工 | P0 配置 |
| 建造部门 | 目标 100 级 | 先 60 级，钢框架后 300 建造力 | 分阶段：1840 前 60，铁框架后 100 | P0 + P1 |
| 贸易中心 | 全国 60、单州 50 | 开局 10；后期人多降回 1 | 保留 50（调研：约 900/级/周），加“后期降级”规则 | P1 |
| 大学 | 固定 50 级 | 创新上限 + 3–5 缓冲；后期 100 所 | 改动态目标：`cap + buffer`，早期约 23–30，富时 100 | P1 |
| 行政 | 80 级，税浪费 5% 就建 | 前期不追；传统主义废除后再建 40 级 | 上限 40；传统主义未废除或基建 <20 时不建 | P0 + P1 |
| 科技 | 经验主义第一；钢框架第 11；漂白/罐头拉黑 | 证券交易所第一；漂白/铁路/水管/转炉/机械工具 → 钢框架 | 重排；解除 `chemical_bleaching`、`canneries` 黑名单 | P0 配置 |
| 法律 | 农本主义、寡头、佃农、人均税、良心自由、公立、职业军队、技术治国、保护主义、商业农业、自由放任 | 佃农→经济干预→人均税→公立学校；不要农本主义/职业军队/贸易保护 | 删农本主义、职业军队、技术治国、保护主义、商业农业；保留寡头修合法性 | P0 配置 |
| 公司 | 纺织/纸/钢/家居/食品/金属/林业/矿业，只建不删 | 纸→建设→精密工具→钢/军工；过渡公司要删 | 加“公司替换/删除”，优先纸/建设/精密工具 | P1 + P2 |
| 外交 | 对 6 国改善关系；接受使馆/贸易特权 | 先给 8 个列强贸易特选；送金币；给 5 年义务换使馆/法律承诺 | 加 `trade_privilege`、`gift`、`law_commitment`、`embassy` 主动动作；拒绝投资权/15 年义务 | P1 + P2 |
| 朝贡/授权 | 无 | 收 10 个朝贡国，拿“附近研究”等 buff | 新增观察 + 动作 | P2 |
| 天朝上国 | 无（`bloc()`/`form_country()` 有接口） | 受认可后成立，拿教育原则 | 新增原则配置 | P2 |
| 脆弱的统一 | 只在事件层硬编码 | 开局 5 点，失败 −1；≤0 分裂 | 观察 JE 计数器 + 法律/战争守卫 | P2 |
| 战争 | 只有军饷姿态 | 200 营 + 炮打尼泊尔/缅甸；俄罗斯承认战争 | 补军队/前线/战争目标/和平模块 | P2 |
| 伐木 PM | 无软/硬木配比 | 大部分软木，3 处硬木 | 新增伐木 PM 规则 | P1 |
| 玻璃/钢/工具 | 建造队列有钢/工具，无玻璃 | 钢框架前先扩玻璃/钢/工具 | 加 `building_glassworks` 优先级与钢框架前预建 | P1 |
| 运动 | `bolster` 清空 | 扶持现代化/自由，打压传统主义 | 定向扶持（实验），不追 activism | P1 实验 |
| 事件 | 只硬编码鸦片 | 义和团选“扶清灭洋”；太平天国拖延 | 补义和团/太平天国选项 | P2 |

---

## 3. P0：`strategy.json` 可直接改的配置

### 3.1 科技

`country_profiles.CHI.tech_priority` 前 12 项改为：

```json
["stock_exchange", "colonization", "empiricism", "central_archives", "dialectics",
 "chemical_bleaching", "railways", "watertube_boiler", "bessemer_process",
 "mechanical_tools", "steel_frame_buildings", "corporate_charters"]
```

后续按 v5 保留：`currency_standards, urbanization, urban_planning, modern_sewerage, mutual_funds, romanticism, line_infantry, napoleonic_warfare, artillery, army_reserves, general_staff, ...`

`tech_blacklist` 删除两项：

```diff
- "chemical_bleaching",
- "canneries",
```

保留：`analytical_philosophy, fractional_distillation, baking_powder, crystal_glass, rubber_mastication, vulcanization, aniline, pumpjacks`。

### 3.2 法律路线

`country_profiles.CHI.law_route` 改为：

```json
[
  ["lawgroup_trade_policy", "law_mercantilism"],
  ["lawgroup_distribution_of_power", "law_oligarchy"],
  ["lawgroup_land_reform", "law_tenant_farmers"],
  ["lawgroup_economic_system", "law_interventionism"],
  ["lawgroup_taxation", "law_per_capita_based_taxation"],
  ["lawgroup_church_and_state", "law_freedom_of_conscience"],
  ["lawgroup_education_system", "law_public_schools"],
  ["lawgroup_distribution_of_power", "law_census_voting"],
  ["lawgroup_policing", "law_secret_police"],
  ["lawgroup_health_system", "law_public_health_insurance"],
  ["lawgroup_economic_system", "law_laissez_faire"]
]
```

要点：

- **删除** `law_agrarianism`（攻略明确“不要改农本主义”；它只是跳自由放任的中转，v5 却被它卡住）；
- **删除** `law_professional_army`（v3 实测 97.3% 占着立法槽）；
- **删除** `law_technocracy`、`law_protectionism`、`law_commercialized_agriculture`（攻略没有，且贸易保护会妨碍贸易特选）；
- **保留** `law_oligarchy`：调研证明独裁上限 2 是合法性根因，攻略也不反对寡头；
- **`law_census_voting` 标为实验项**：攻略用它压士大夫，但调研 #12 说财产投票会让士大夫更强。先放在路线里但单独跑一组，失败就回滚；
- **不要**加 `law_state_religion`（调研 #16：国教会让藏/维接受度掉到文化抹除；攻略的“国教加速同化”收益不值得默认开）。

### 3.3 财政

```json
"budget": {
  "min_tax": "Medium",
  ...
}
```

```json
"consumption_tax": {
  "goods": ["services", "tea"],
  "max_goods": 1,
  "keep_when_low_sol": 1,
  ...
}
```

`services` 已在 `data/goods.json` 里（zh=服务），可以直接用。中期（SoL ≥ 10、预算充足）再把 `max_goods` 提到 2，只加高档衣服/瓷器。

```json
"subsidies": {
  "max_per_month": 1,
  "max_total_share": 0.015,
  ...
}
```

### 3.4 大学 / 行政 / 贸易中心 / 建造部门

```json
"universities": {
  "target_levels": 30,
  "max_per_state": 3,
  "max_per_month": 2,
  ...
}
```

说明：30 是早期基线；P1 再加“动态创新上限 + 3–5 缓冲”的规则，动态值覆盖这个固定值。

```json
"construction": {
  "admin_max_total_levels": 40,
  "admin_min_tax_waste": 0.08,
  "construction_sector_max_levels": 100,
  ...
}
```

P1 加阶段规则：1840 前最多 60 级；铁框架后 100 级。

`trade_center` 保持 `target_levels: 50`、`target_total_levels: 60`（调研：贸易中心回报最高），P1 加“后期降级”规则。

### 3.5 建造与商品优先级

`priority_goods` 增加玻璃、硬木：

```json
"priority_goods": {
  "iron": 1.5, "coal": 1.4, "tools": 1.4, "wood": 1.35, "steel": 1.35,
  "glass": 1.25, "hardwood": 1.2,
  "meat": 1.3, "fabric": 1.15, "clothes": 1.15, "furniture": 1.15,
  "paper": 1.15, "groceries": 1.1
}
```

`construction.priority_queue` 增加玻璃、钢、工具、牧场：

```json
"priority_queue": {
  "building_textile_mill": 2,
  "building_furniture_manufactory": 1,
  "building_paper_mill": 1,
  "building_food_industry": 1,
  "building_logging_camp": 2,
  "building_iron_mine": 1,
  "building_coal_mine": 1,
  "building_tooling_workshop": 1,
  "building_glassworks": 2,
  "building_steel_mill": 1,
  "building_livestock_ranch": 1,
  "building_railway": 1,
  "building_port": 1,
  "building_financial_district": 1
}
```

### 3.6 公司

`companies.preferred` 改为：

```json
["company_basic_paper", "company_basic_textiles", "company_basic_steel",
 "company_basic_tooling", "company_basic_metalworks", "company_basic_home_goods",
 "company_basic_food", "company_basic_forestry", "company_basic_metal_mining"]
```

注意：攻略里的“统一建设联合体”“精密工具”英文 key 未在仓库里确认，P1 先用 `GetAvailableCompanies` 输出核对，再补进列表；不要硬编码猜 key。

### 3.7 外交

```json
"diplomacy": {
  "improve_relations": ["GBR", "RUS", "FRA", "PRU", "AUS", "USA", "OTT", "SPA"],
  "grant_trade_privileges": ["GBR", "RUS", "FRA", "PRU", "AUS", "USA", "OTT", "SPA"],
  "gift_budget": 5000,
  "obligation_max_years": 5,
  "reject_investment_rights": true,
  "request_embassy": true,
  "request_law_commitment": ["law_interventionism", "law_public_schools"],
  ...
}
```

`reject_keywords` 里**删除** `"义务"`（攻略明确给 5 年义务换条约），改为代码判断“15 年义务才拒绝”。

---

## 4. P1：小改代码（不改架构）

1. **`runner.handle_military()` 扩展为工资策略**
   - 增加 Government：日期 < 1842、非战时、`balance < 0` 或 `money < 6 个月开支` → Low；否则 Medium。
   - Military 保持 Medium；战时 High。
   - 新增 `strategy.json` 的 `wages` 配置块。

2. **`companies.py` 加替换/删除**
   - 读 `CompanyInfo` 的现有公司；按 `company_replace_after` 配置，把纸张/建设公司替换成钢/军工/精密工具。
   - 需要新增 `Actions.remove_company()`（先确认游戏 API 有 `RemoveCompany`；没有就用 `company` 的反向命令）。
   - 公司升级到 3 级：确认 `Actions.company()` 是否支持 `upgrade`。

3. **`construction.py` 伐木 PM**
   - 新增规则：伐木建筑默认 `pm_softwood`；保留 3 个州 `pm_hardwood`；硬木价格 > 软木 ×1.5 时切换。
   - 配置：`logging.softwood_target_ratio`, `logging.hardwood_states`。

4. **`construction.py` 钢框架前预建**
   - 当 `steel_frame_buildings` 将在 24 个月内完成（或已研究）时，提高玻璃/钢/工具的优先级；玻璃价格 >1.3 时强制先扩玻璃。
   - 配置：`construction.steel_frame_prebuild_months: 24`。

5. **`diplomacy.py` 主动动作**
   - 开局：对 8 个列强依次 `trade_privilege`（99 年），成功后 `improve_relations`。
   - 承认 JE 激活：对每个列强请求 `embassy`；有预算时送 `gift`（≤5000/月）。
   - 立法卡住：对西班牙/普鲁士请求 `law_commitment`（经济干预/公立学校）。
   - 义务：只接受 ≤5 年；15 年拒绝。
   - 需要补观察字段：`relations`, `trust`, `obligations`, `proposal details`。

6. **`trade.py` 早期主动进口**
   - 1836–1840 对木材/硬木/铁做“进口零关税”常开，不等缺货；对茶叶做出口高关税。
   - 配置：`trade.proactive_imports: ["wood","hardwood","iron"]`。

7. **`politics.py` 法律承诺加成**
   - 如果当前法律有 `law_commitment` 加成，降低 `min_pass` 门槛（例如 0.35 → 0.25）。
   - 配置：`politics.commitment_bonus: 0.10`。

8. **`politics.py` 脆弱的统一守卫**
   - 读 `je_warlord_china` 的计数器；≤2 时禁止推 `lawgroup_distribution_of_power` 的君主制改动；≤1 时禁止借款/政变/内战选项。
   - 需要 `actions.journal()` 返回 counter 字段（当前可能只有 key/progress）。

9. **`observe.py` 补字段**
   - `journal` 进度/计数器；`movements` 的支持率与意识形态；`bloc` 原则；`subjects`/朝贡；`trust`/`obligations`；公司等级。

---

## 5. P2：新系统（需要观察层 + 动作）

1. **天朝上国 power bloc**
   - 受认可后 `form_country("天朝上国")`；用 `bloc()`/`upgrade_principle()` 拿教育/研究原则。
   - 需要确认 `bloc()` 返回的原则列表与 `upgrade_principle` 的 index 语义。

2. **朝贡国 / 授权**
   - 收不丹、尼泊尔、缅甸、越南、朝鲜等为朝贡国；凑 10 个解锁第三/第四栏。
   - 需要 `diplomatic_actions()` 里的“make tributary”动作，以及 `subjects` 观察字段。
   - “附近研究”buff：减少学校行政力、加科技速度。

3. **脆弱的统一完整守卫**
   - 观察计数器 + 事件/法律/战争三处联动；≤1 时禁止君主制改动，避免军阀时代。

4. **战争模块**
   - 军队编制：200 营线列 + 50 炮 + 50 征召；合并编队、升将军、将军忠诚 > −5。
   - 战争目标：尼泊尔/缅甸朝贡；俄罗斯 Humiliation + 解放目标（二选一）。
   - 和平：白和/执行目标；不要 Capitulate。
   - 需要 `war support`、`front`、`battalion`、`war goal` 观察字段。

5. **公司生命周期**
   - 建 → 升级到 3 级 → 替换/删除过渡公司。

6. **事件**
   - 义和团：选“扶清灭洋”（第一个），接受 −1 脆弱统一换天命 buff；
   - 太平天国：`heavenly.4` 选“碾碎”；`heavenly.5` 选“仁慈/赦免”；
   - 传教士：`CHI_missionaries.2` 处决；`.3/.4` 欢迎。

---

## 6. 与既有调研的冲突与取舍

| # | 冲突点 | 攻略 | 调研/实测 | v6 取舍 |
|---|---|---|---|---|
| 1 | 政府/军队工资 | 极低 | Medium 只多花 19k/周，但 Low 掉认可/训练 | 政府 Low（限 1842 前、非战时、现金紧）；军队 Medium |
| 2 | 大学数量 | 23 所吃满上限，富时 100 所 | 30 级在 23% 识字率下足够；v4-economy 93 所拖垮建造力 | 动态“上限 + 3–5”，早期 23–30；100 所只在富时 |
| 3 | 贸易中心 | 开局 10，后期降 1 | 约 900/级/周，回报最高 | 保留 50；加“后期人多降级”规则 |
| 4 | 自由贸易 | 大后期改自由贸易 | 自由贸易会解除鸦片禁令，−20% 权威 | **不改自由贸易**，重商主义用到结档 |
| 5 | 国教 | 学校后改国教，加速同化 | 国教让藏/维接受度掉到文化抹除 | 默认不开；单独实验 |
| 6 | 资格性选举 | 压士大夫、扶小市民 | 财产投票会让士大夫更强（调研 #12） | 标为实验项，单独跑 |
| 7 | 职业军队 | 攻略未强调 | v3 卡在 97.3%，占立法槽 | 主路线删除；只在开战前需要时插入 |
| 8 | 农本主义 | 明确“不要改” | v5 被农本主义卡住 | 主路线删除 |
| 9 | 漂白/罐头黑名单 | 攻略要用 | 调研列为时代 5 陷阱 | 解除黑名单；只在前置命中时研究 |
| 10 | 建造部门 60 vs 100 | 60 级 + 钢框架 | v3 的 100 级/210 建造力是 SoL 主支撑 | 分阶段：1840 前 60，铁框架后 100 |

---

## 7. 验收与测试

1. `python -m pytest tests -q` 全绿（当前基线 75–87 个测试，以实跑为准）。
2. 12 个月冒烟：`python scripts/play.py --save v3mcp_start_1836 --months 12 --label v6-smoke`。
3. 300 个月主跑：`--months 300 --label v6-guide`；对照 v3（1836→1846）与基线。
4. 重点指标：
   - 人均 GDP、SoL（主指标）；
   - 建造力（1840 前 120+，1850 前 210+）；
   - 钢框架完成时间（目标 ≤1862）；
   - 识字率（目标 1846 前 25%+，1856 前 40%+）；
   - 法律数（10 年 ≥3 条，不再只 1 条）；
   - 公司数/实业家 clout；
   - 承认 JE 进度；脆弱的统一计数器。
5. 每组实验（census voting / state religion / free trade）单独 label，失败即回滚。
6. 结果写回 `docs/research-progress.md`；用户明确要求时才 commit/push。

---

## 8. 建议实施顺序

1. **P0 配置**（本文件 §3）：先改 `tech_priority`、`tech_blacklist`、`law_route`、`budget.min_tax`、`consumption_tax`、`subsidies`、`universities`、`admin_max_total_levels`、`priority_goods`、`priority_queue`。
2. 跑 `pytest` + 12 个月冒烟，确认没有断言失败和明显回退。
3. **P1-a**：政府工资、伐木 PM、钢框架预建、公司替换。
4. **P1-b**：外交主动动作（贸易特选/礼物/使馆/法律承诺）、被动进口。
5. **P1-c**：脆弱的统一守卫、观察字段。
6. **P2**：天朝上国、朝贡、战争模块。
7. 300 个月主跑与对比。

---

## 9. 实施状态（2026-10-24）

### 已完成并测试

- **P0 配置**：税级下限 Medium；消费税改 `services`（茶兜底）1 项；补贴 1.5%/每月 1 个；大学 30 级起/每月 2 级；行政 80→40；科技顺序重排（证券交易所→殖民→经验主义→漂白→铁路→水管→转炉→机械工具→钢框架）；解除 `chemical_bleaching`/`canneries` 黑名单；法律路线删农本主义/职业军队/技术治国/保护主义/商业农业，加资格选举/秘密警察；建造优先级加玻璃/钢/牧场；商品优先级加玻璃/硬木；公司纸张优先；外交 8 列强。
- **P1-a**：
  - `budget.government_wage_level()` + `runner.handle_military()`：1845 年前、重商主义前、非战时政府工资 Low，之后 Medium；军队始终 Medium/High。
  - `production.logging_candidates()`：大部分伐木营优先软木，保留 2–4 个州专注硬木，按硬木/软木价格比调整。
  - `construction.steel_frame_multiplier()`：转炉/钢框架科技后，玻璃/钢/工具建筑评分 ×1.6。
  - `companies.candidates()`：1861 年后解散纸张公司，为钢公司腾槽。
- **P1-b**：
  - `diplomacy.match_action()` + `runner.handle_diplomacy()`：贸易特选 / 使馆 / 法律承诺 / 赠礼主动动作，再改善关系。
  - `trade.candidates()`：1845 年前对木材/硬木/铁主动进口零关税。
- **P1-c**：
  - `politics.guard_fragile_unity()`：脆弱统一 ≤1 点时跳过权力分配法律组。
  - `Memory.fragile_unity` + `handle_journal()`：从 `je_warlord_china` 进度条读取剩余点数。
- **P2 部分**：
  - `runner.handle_subjects()`：对尼泊尔/缅甸/暹罗/越南/朝鲜尝试合法朝贡/保护国行动。
  - `runner.handle_bloc()`：已入集团时按“教育/研究/贸易/建设”顺序升级原则。
- **测试**：`python -m pytest tests -q` → **100 passed**。
- **12 个月冒烟**（1836.1.1 → 1837.1.1，同存档对照）：

| 指标 | 基线 | v6 |
|---|---:|---:|
| GDP | 95.06M | 94.69M |
| 国库 | 9.78M | **11.60M** |
| 建造力 | 22 | **35.9** |
| SoL | 8.38 | **8.66** |
| 识字率 | 15% | **17%** |

所有动作 0 失败；政府工资 Low、服务税、主动进口、伐木 PM 轮换、证券交易所优先均已实测生效。

- **120 个月结果**（1836→1846）：GDP 120.3M、SoL **7.85**、识字率 **30%**、建造力 178、国库 14.6M；对比 v3（119.8M / 6.94 / 21% / 210 / 16.6M），SoL 与识字率大幅领先，建造力低 32。
- **法律停滞 bug**：v6 前 10 年只过 1 条法律、停滞 92 个月。根因是兜底法律不在 `law_options` 的路线过滤列表，`observe` 读不到。已加 `politics.fallback_route` + `runner.advise()` 扩展过滤列表；100 tests passed，待复跑验证。
- **建造力卡 32 的 bug**：`construction.candidates()` 的 `have` 把排队中的建造部门也算进预算上限；完成约 11 级、排队 29 级时 `have=40`、`cap≈41`，`want=0`，建造力停在 32。已修为只按已完成等级计算，并新增 `construction_rush`（60 级前每月 8 级、45% 收入、允许 6% 赤字、只排部门+粮食）；1845 年前铁价阈值 1.0。101 tests passed。
- **冲刺版 12 个月实测**：建造力 22 → **191.9**（普通 v6 35.9，UP 202）；SoL 7.84（普通 8.66）、识字率 16%（普通 17%）、国库 8.19M（普通 11.60M）。1836.10 已到 192 = 60 级 + 铁框架。

### 未完成（需要游戏/观察层或更多转写）

- **全量转写已完成**：进阶 1/2 剩余 3.7 小时已转写，补充见 §10；不再有转写缺口。
- **战争模块**：需要 war support、前线、营数、战争目标观察字段；当前只有军饷姿态。
- **天朝上国成立**：`Actions.form_country()` 有接口，但需要确认 formation key 与“受认可”观察字段。
- **外交观察**：relations / trust / obligations / proposal 方向仍缺，主动动作只能靠 `valid` 与 `why_not` 试探。
- **游戏内复测**：12 个月冒烟 → 120 个月 → 300 个月；需要游戏运行 + 桥接 `127.0.0.1:8766`。

### 改动文件

- `src/agent/data/strategy.json`（P0/P1/P2 配置）
- `src/agent/strategy/budget.py`（政府工资）
- `src/agent/strategy/production.py`（伐木 PM）
- `src/agent/strategy/construction.py`（钢框架预建）
- `src/agent/strategy/companies.py`（公司替换）
- `src/agent/strategy/diplomacy.py`（行动匹配）
- `src/agent/strategy/trade.py`（主动进口）
- `src/agent/strategy/politics.py`（脆弱统一守卫）
- `src/agent/strategy/plan.py`（接入伐木 PM）
- `src/agent/runner.py`（工资/外交/朝贡/集团/脆弱的统一）
- `tests/test_strategy.py`（新增 11 个测试）

---

## 10. 全量转写补充（2026-10-24 晚）

覆盖率从 41% → **100%**：宝宝巴士 114.8 分钟、进阶 1 105.5 分钟、进阶 2 156.5 分钟全部转写。以下是新增/修正。

### 10.1 法律（含一个真实 bug）

- **`law_secret_police` 属于 `lawgroup_internal_security`，不是 `lawgroup_policing`**——v5/v6 原路线写错了组，已修。
- `law_dedicated_police`（专职警察部队，需 `law_enforcement`）是警察线毕业；`law_local_police` 会让地主更强，不要用。
- `law_corporate_state`（法团国家，需 `corporatism`，governance_principles）是当前版本最强政体：高合法性 + 可改合作社；晚期接在资格选举之后。
- `law_graduated_taxation`（累进税，需 `socialism`）：人均税是过渡，累进税毕业。
- `law_old_age_pension`（养老金，需 `human_rights`）、`law_womens_suffrage`（需 `feminism`）、`law_compulsory_primary_school`（需 `human_rights`）是晚期 SoL 毕业线。
- 学校/医院机构要升到 5 级，识字率才到 99.9%；**不要升行政机构的生产方式**（纸翻倍、行政只 +30%、征税 +50%，人多时多建楼更划算）。v6 已加 `institutions_late`：1860 后国库 >1.5× 储备上限时教育/卫生升到 5 级。
- 自由贸易：攻略说大后期可改，但调研实测会解除鸦片禁令（−20% 权威），v6 仍保持重商主义；这是保留的分歧。
- 文化多元：只有吃外国地时才需要，且要先打压“中国至上”；不吃地不改。

### 10.2 财政

- **晚期国库充足时降税到 Low**，把钱留在人民手里拉动内需/SoL。v6 已加 `late_low_tax_*`：1861 后、国库 >1.5× 储备上限、结余 >10% 收入才触发。
- 消费税：钱多时可以直接取消，提升 SoL 的幅度不大，但方向正确。
- 福利：工资补贴前中期，养老金晚期；济贫法不要。
- 补贴：**玻璃不要补**（过剩就倒海里）；v6 已把 `building_glassworks` 从补贴列表移除。

### 10.3 大学 / 公司 / 生产

- 大学：23 所吃满 15% 识字率的创新上限；40% 识字率约 60 所；1860 后国库充足再堆 100 所吃 20% 效率扩散。v6 已加动态目标（`university_target`）。
- 公司：纸张第一（+10% 行政、政府/大学吞吐、征税能力），后期删；工具/兵器/钢/食品强，食品公司 +20 SoL；瓷器一般；波西米亚玻璃强但需要欧洲地。v6 公司顺序已改为 纸→钢→食品→纺织。
- 建筑收益：汽车 > 工具 > 钢 > 电子厂（电子厂/电话机挤占运力，害铁路）；艺术学院不要造；发电厂解锁后每州 1 级，先亏后赚。
- 铁路：在基础设施低的地方造，开轨道运输 PM，微调年均产值；补贴很少，后期忽略。
- 行政机构：人多时多建楼，人少时再升 PM。

### 10.4 贸易

- **晚期国内资源耗尽：铁/木材/硬木给进口补贴**。v6 已加 `late_import_subventions`：1861 后价格 >1.5× 触发、结余为正。
- 便宜商品用出口补贴往外倒，拉就业和 GDP；财政要扛得住。
- **不要给投资权**：列强会在你国内建鸦片厂，失业上涨。

### 10.5 军事 / 吞并

- 陆军成型：约 **440 营 = 200 步兵 + 100 炮兵 + 100 骑兵 + 40 步兵**；袁世凯（科技点完后）可带 440。
- 装备：飞机侦察、卡车运输、医院恢复最强；坦克晚期。登陆英国用超级无畏舰 + 海军入侵，只吃本土，不吃海外地。
- 朝贡：朝鲜独立度掉到 25 时降为保护国；你的陆军投射是对方的 5–10 倍才会持续降独立。
- 吃外国地必须改文化多元，否则爆分离。

### 10.6 太平天国 / 事件 / 脆弱的统一

- 传教工作选第一个加速太平天国；拜上帝会 4 个地区、动乱 >15 才爆；爆发前把福建等地的老兵兵营删掉，叛军只有新兵。
- `heavenly.4` 选“碾碎”，不要 play as 太平天国；胜利后吞并，`heavenly.5` 选“展示仁慈”（避免基督教列强 −25 关系）。
- 脆弱的统一：革命/政变/内战各 −1；保持 ≥2 点才改君主制；1 点改君主制瞬间分裂（v6 已有 ≤1 守卫）。
- 义和团：攻略通常让它失败（−1 点），成功线时间也不好；3 点失败到 2 点仍可改君主制。
- 琉球事件：给 1000 块，选“尊崇文的大军”拿 +3 影响力。

### 10.7 天朝上国 / 权力集团

- 受认可后立即成立国家；权力集团必须在贸易联盟/内部贸易里选一个；原则优先教育/研究（普鲁士教育加同化，附近研究加科技速度）。
- v6 已接 `handle_bloc` 按原则名升级；成立国家/创建集团仍需确认 formation key 与受认可观察字段。


### 10.8 2026-10-24 时间线合并后的修正

- 新增 [up_timeline.md](up_timeline.md)，合并 stage1–4 + 画面数据。**stage3/stage4 把顶栏 GDP/人口写反**：1855-10 UP 真实 **GDP 161.4M、人口 434M**；1843–55 人均 GDP 是 **+21.3%**，不是 -17.6%。
- 因此 v6 1858-11（GDP 122.7M、人口 397M、人均 309）对 UP 1858-11（GDP 157.7M、人口 438M、人均 360）是 **人均 -14%**，不是总量 -70%。真正的大差距是建造力（184 vs 610）、识字率（24% vs 38.2%）和 SoL（7.36 vs 7.8）。
- 610 = **200 级铁框架**；100 级约 310；钢框架 1861 才切，200 级约 810。
- 代码新增：法律兜底 24→6 个月；`law_vanished` 立法失败次月立即启用兜底；`input_recovery`（铁/工具/煤/木材短缺时保底 2 个上游槽）；`sol_recovery`（SoL<8 时保底 2 个消费品槽）。105 tests passed，待下一局验证。
