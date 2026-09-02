# Custom v0 功能设计（通用学习系统 · 最小闭环）

> 状态：设计稿（配合 `Custom-定位与需求-v2.md`；待 D1/D3 定夺集成细节后定稿）
> 建立：2026-09-02
> 目标：把"通用底层学习系统"落成一组**可执行的功能模块、数据结构、核心流程**，作为 v0 实施蓝图。

---

## 一、v0 最小闭环（一条自洽的使用路径）

> 目标 → 四拍循环 → 每日两勾 → 讲题卡 → 判定卡验收 → 周复盘

```
首次(冷启动)
  输入目标（倒着写结果："我学会了…"）→ 生成默认学习习惯系统
日常
  打开 → 今日该做什么（四拍循环的某一步）→ 每日两勾（独立做题 + 讲题）
  讲题 → 讲题卡四格 → 提交 → AI 辅助判定（岔路口制）→ 过/不过 + 卡在哪
周
  周成果卡四行（做对几道/讲通一题/卡壳集中/下周改一点）→ 趋势复盘（看趋势不看单次）
  随机抽一天抽查防注水（"这天勾了'做了题'，做的哪道？卡在哪？"）
始终
  streak 可视化（连续天数）→ AI 提醒（24h 错峰 / 7 天停推 / 被动攻击式沟通）
```

---

## 二、功能模块划分

| 模块 | 职责 | 复用现有 |
|---|---|---|
| **core.goal** | 目标层：输入目标（倒着写结果）、解析"我学会…"，生成默认系统 | `goals`（改名复用） |
| **core.cycle** | 四拍循环元模型：问题→猜想→验证→输出；把今日动作映射到某一步 | 🆕 |
| **core.card** | 讲题卡四格（考什么/为何/卡在哪/下次信号）+ 判定卡（岔路口三率） | 🆕（**核心新增**） |
| **core.verdict** | 岔路口判定：看懂率=复述岔路口≥一半且≥1；讲对率=骨架+扛住追问≥1+卡壳自指；**不用百分制**，只记过/不过+卡点 | 🆕（判定逻辑） |
| **core.log** | 每日两勾（独立做题/讲题）+ 连续/进度记录 | `attempts`（改语义） |
| **core.streak** | 连续天数计算 + 断签规则 + 提醒调度（24h 错峰/7 天停推/被动攻击式） | 🆕 |
| **content.channel** | 内容通道抽象：一条通道 = 一套锚点题/例题/题源；v0 = 数学通道 | `stages/tasks` + 高考数学工作区题源 |
| **content.topdown** | 自顶向下八步内容范式（锚点题六标准→拆解→补概念→求解→验证→方法卡） | `planner`（改造） |
| **api** | FastAPI 路由 + 错误映射 + 静态伺服 + LLM client 工厂 | `main.py`（复用） |
| **store** | SQLite CRUD（参数化/外键/级联/错误约定） | `store.py`（复用+扩表） |
| **frontend** | 原生单页：今日视图/讲题卡/判定/周成果/streak | `frontend/`（改造） |

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
