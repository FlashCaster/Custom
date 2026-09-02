# Custom v0 功能设计（通用学习系统 · 最小闭环）

> 状态：设计稿（**App 端**版；配合 `Custom-定位与需求-v2.md`；待 D1/D3 定夺集成细节后定稿）
> 建立：2026-09-02 · 2026-09-02 更新为「学生五时间块 × 阶梯」主框架
> 目标：把"通用底层学习系统"落成一组**可执行的功能模块、数据结构、核心流程**，作为 v0 实施蓝图。
> **双版本说明**：本文档是 **App 端**（自用简化版，无动机对照实验）；**实际服务版（老师带，含对照实验）**见 Obsidian `Projects（项目）/Custom/服务设计.md`。

---

## 〇、主框架：学生五时间块 × 每块阶梯

> 学生的一天由五个时间块构成；系统**按时间块**给"循序渐进的阶梯步骤"（由易到难）。这取代早期抽象的"四拍循环"作为主引导框架；四拍循环/判定卡等作为**后台 AI 判标逻辑**，不进学生日常。

| # | 时间块 | 性质 | 状态 |
|---|---|---|---|
| ① | 预习 | 输入准备 | ✅ 已设计（App 版见 §一） |
| ② | 上课 | 输入 | ⏳ 待设计 |
| ③ | 课后练习 | 输出+验证 | ⏳ 待设计 |
| ④ | 考试测验 | 检测+反馈 | ⏳ 待设计 |
| ⑤ | 反思总结 | 沉淀 | ⏳ 待设计 |

> 原则：**先解决"为什么做"（动机），再给循序渐进的阶梯。** 纸笔、无手机、低成本执行。

---

## 一、v0 最小闭环（一条自洽的使用路径）

> 目标 → 每个时间块按"当前档位"执行 → 每日卡汇总 → streak 可视化 → AI 提醒

```
首次(冷启动)
  输入目标（倒着写结果："我学会了…"）→ 生成默认学习习惯系统（五块 + 各块当前档位 L1）
日常
  打开 → 今日各块该做什么（按各块"当前档位"）→ 纸笔每日卡（每块一行）
  每块达档 → 档位可进阶（L1→L2→…，循序渐进）
周
  周成果（做对几道/讲通一题/卡壳集中/下周改一点）→ 趋势复盘（看趋势不看单次）
始终
  streak 可视化（连续天数）→ AI 提醒（24h 错峰 / 7 天停推 / 被动攻击式沟通）
```

### ① 预习 · App 端版（无对照实验，只给提示）

> 对照实验在 App 内**不好做/无老师带**，故 App 端**不内置实验**，改为给用户**提示**让他自己去试；动机说理 + 案例给一次性带入提示即可。

- **动机提示（一次性/可查看）**：App 在首次进入预习块时给一段"你会不会'听得懂但做不出'？预习是让你带着卡点去上课"的轻提示 + 1 个案例（如"同桌预习过，老师问 y=log₂x 定义域秒答"），并引导"想自己验证？试试：选一个没学过的知识点，先标出你卡在哪，再去上课/看课，对比一下效果。"
- **阶梯（与老师版一致的 L1-L4，供自助）**：

| 档次 | 步骤 | 成本 |
|---|---|---|
| L1 | 过一眼：快速看明天要讲的，知道大概讲什么 | 1 分钟 |
| L2 | 标疑问：把看不懂的标 1-2 处，写"我卡在___" | 2 分钟 |
| L3 | 试着做：挑 1 道例题/最简单题独立做，标卡在哪 | 3-5 分钟 |
| L4 | 带问题上课：把疑问整理成 1-2 个"明天我要听/验证"的问题 | 全程 |

- **App 后台**：生成预习单（根据课表/章节，预判"最该看哪段、最容易卡在哪"）；记录用户"卡点"（→ 趋势 + 后续选题依据）。**

---

## 二、功能模块划分

| 模块 | 职责 | 复用现有 |
|---|---|---|
| **core.goal** | 目标层：输入目标（倒着写结果）、解析"我学会…"，生成默认系统 | `goals`（改名复用） |
| **core.block** | **五时间块**元模型（预习/上课/课后练习/考试测验/反思总结）+ 各块**当前档位**（L1→L4）与进阶规则 | 🆕（主引导框架） |
| **core.card** | 讲题/每日卡（每块一行：当前档位的动作 + 卡点） | 🆕 |
| **core.verdict** | 岔路口判定（看懂率/讲对率，**不用百分制**）——作为后台判标 | 🆕 |
| **core.log** | 每日各块记录（每块当前档位完成与否 + 卡点）+ 连续/进度 | `attempts`（改语义） |
| **core.streak** | 连续天数计算 + 断签规则 + 提醒调度 | 🆕 |
| **content.channel** | 内容通道抽象：一条通道 = 一套锚点题/例题/题源；v0 = 数学通道 | `stages/tasks` + 高考数学工作区题源 |
| **content.topdown** | 自顶向下八步内容范式（后台生成/校验） | `planner`（改造） |
| **api** | FastAPI 路由 + 错误映射 + 静态伺服 + LLM client 工厂 | `main.py`（复用） |
| **store** | SQLite CRUD（参数化/外键/级联/错误约定） | `store.py`（复用+扩表） |
| **frontend** | 原生单页：五块今日视图/档位进阶/周成果/streak | `frontend/`（改造） |

---

## 三、数据结构（v0，单用户无 user_id，沿用现有库到 `data/custom.db`）

```sql
-- 目标层（改名复用 goals）
CREATE TABLE IF NOT EXISTS systems (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  target TEXT NOT NULL,             -- "我学会了…"（倒着写结果）
  created_at TEXT NOT NULL
);

-- 每日日志 / 两勾（改 attempts 语义，或新表 daily_logs）
CREATE TABLE IF NOT EXISTS daily_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  system_id INTEGER NOT NULL REFERENCES systems(id) ON DELETE CASCADE,
  date TEXT NOT NULL,
  did_problem INTEGER NOT NULL DEFAULT 0 CHECK (did_problem IN (0,1)),  -- 独立做题
  did_explain INTEGER NOT NULL DEFAULT 0 CHECK (did_explain IN (0,1)),  -- 讲题
  note TEXT DEFAULT '',
  UNIQUE(system_id, date)
);

-- 讲题卡（输出层：四格结构化）
CREATE TABLE IF NOT EXISTS explain_cards (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  log_id INTEGER NOT NULL REFERENCES daily_logs(id) ON DELETE CASCADE,
  problem TEXT NOT NULL,
  s_what TEXT DEFAULT '',       -- ① 这题考什么
  s_why TEXT DEFAULT '',        -- ② 第一步为什么这么做
  s_stuck TEXT DEFAULT '',      -- ③ 卡在哪一步、为什么
  s_signal TEXT DEFAULT '',     -- ④ 下次看到什么信号就想到这招
  done INTEGER NOT NULL DEFAULT 0 CHECK (done IN (0,1)),  -- 四格说出口+讲满3min+卡壳自指
  ts TEXT NOT NULL
);

-- 判定记录（验收层：岔路口制，不用百分制）
CREATE TABLE IF NOT EXISTS verdicts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  card_id INTEGER NOT NULL REFERENCES explain_cards(id) ON DELETE CASCADE,
  crossings TEXT NOT NULL,          -- json 岔路口列表
  rate_do INTEGER NOT NULL CHECK (rate_do IN (0,1)),      -- 做对率
  rate_see INTEGER NOT NULL CHECK (rate_see IN (0,1)),    -- 看懂率（复述≥一半且≥1）
  rate_explain INTEGER NOT NULL CHECK (rate_explain IN (0,1)), -- 讲对率（骨架+追问+卡壳自指）
  pass INTEGER NOT NULL CHECK (pass IN (0,1)),
  stuck_point TEXT DEFAULT '',      -- 卡在哪（攒≥5 条 → 下次选题依据）
  judge_source TEXT NOT NULL DEFAULT 'ai',  -- ai / user（单用户无老师 → AI 辅助+用户自评）
  ts TEXT NOT NULL
);

-- streak 状态（习惯层）
CREATE TABLE IF NOT EXISTS streaks (
  system_id INTEGER PRIMARY KEY REFERENCES systems(id) ON DELETE CASCADE,
  current INTEGER NOT NULL DEFAULT 0,
  longest INTEGER NOT NULL DEFAULT 0,
  last_active_date TEXT
);

-- 提醒调度（习惯层）
CREATE TABLE IF NOT EXISTS reminders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  system_id INTEGER NOT NULL REFERENCES systems(id) ON DELETE CASCADE,
  state TEXT NOT NULL DEFAULT 'active' CHECK (state IN ('active','muted','stopped')),
  last_sent_at TEXT, last_used_at TEXT,
  inactive_days INTEGER NOT NULL DEFAULT 0
);
```

> 注：是否复用 `goals/paths/stages/tasks/attempts` 原表名，还是新表如上——**由 D1/D3 决定**（D1：方法论是否直接替换现有层级；D3：mastery θ 是否并入）。

---

## 四、关键设计规则（可验证优先）

1. **不用百分制**：验收只记 `pass/不过 + 卡在哪一步`（"85 分"会制造新的自我感觉良好）。
2. **讲通才是输出**：复述≠输出（复读机）、抄错题≠输出（书法课）；判定的是"合上一切能否从零搭出来/讲给别人听懂并能接住追问"。
3. **诚实成本低，说谎成本高**：防注水的核心 = 随机抽查"你勾的这题做的是哪道、卡在哪"；答不上 → 勾选作废。
4. **采样看趋势**：每次只抽 1 题做全三验；每周各 3~5 数据点，看第 N 周 vs 第 1 周，不跟上周比。
5. **校准一次**：一个知识点一次 5 题（2 易 + 2 中 + 1 难）拿基线，不再反复三验。
6. **AI 辅助 + 用户自评**：单用户无"老师"角色时，AI 按岔路口标准给出判定，用户可质询/改判（judge_source 记录），避免过度依赖人工前提。

---

## 五、v0 边界与取舍

**做**
- 通用系统骨架最小闭环（目标→四拍→两勾→讲题卡→判定卡→周复盘）。
- 默认学习习惯系统（冷启动即用，降低门槛）。
- 数学作为**第一条内容通道**（复用高考数学工作区题源/教案/课件）。
- streak + AI 提醒（习惯层）。

**不做（v0）**
- 原 AI 工程师技能路径（待办）。
- 用户定制模块（个性化习惯系统，v0 后）。
- 多用户/云端（本地单用户自用+分享）。
- 深度层 mastery θ 的完整接入 → **待 D3**。

---

## 六、TDD 实施计划（对齐 agents.md 流程规则：每改动必先/同步测试、全绿再交付）

| 步 | 内容 | 测试 |
|---|---|---|
| T1 | `core.verdict` 判定纯函数（岔路口/三率/校准） | 正常+攻击用例（复用 mastery-engine TDD 风格） |
| T2 | `core.streak` 连续天数/断签/提醒调度 | 边界用例（断签/7天停推/被动攻击式） |
| T3 | `core.card` 讲题卡四格 + 完成判定 | 结构化校验 |
| T4 | `store` 新表 + CRUD（参数化/级联/错约） | CRUD+级联+并发 |
| T5 | `api` 路由串通（系统/日志/卡/判定/streak） | TestClient + curl 冒烟 |
| T6 | `content.topdown` 自顶向下生成/校验 | LLM mock + 严格校验 |
| T7 | 前端三区（今日/讲题卡/判定/周成果/streak） | 走查（控制台无错/转义/可走通） |

> 每步红→绿 TDD、每步一推送（沿用 agents.md 规则）。
