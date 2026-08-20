# G3 第 5 步计划：API 路由（goals/paths/tasks/attempts/export 串通 + curl 冒烟）

- 日期：2026-08-20
- 状态：待用户确认（2026-08-20 落盘，随 G3-4 终审交付；确认后待开工指令执行）
- 阶段：全模式 G3 小步实现（TDD）
- 输入：PROJECT_BRIEF.md + docs/G1-方案.md §5 §6 + backend/main.py（G2 stub）+ backend/store.py / checker.py / planner.py 现有契约 + ADR-2026-08-20-checker判分契约

## 1. 实现对象（路由清单，全部 REST/JSON）

| 方法 | 路径 | 功能 | 后端调用 |
|---|---|---|---|
| GET | /health | 健康检查（G2 已有，保留） | - |
| POST | /goals | 建目标 `{statement, interests}` → 201 返回 goal | store.create_goal |
| GET | /goals | 目标列表 → 200 | store.list_goals |
| POST | /goals/{goal_id}/paths/generate | LLM 生成候选：goal.statement+interests → generate → validate → create_path(draft) → 201 完整树 | planner + store |
| POST | /paths/{path_id}/activate | 用户确认候选落地：set_path_status("active") → 200 | store.set_path_status |
| GET | /paths/{path_id} | 路径完整树（stages/tasks 含 id） | store.get_path |
| POST | /tasks/{task_id}/attempts | 完成判定双模：quiz `{answer: int|str}` / artifact `{checklist: [bool]}` → 判分 → record_attempt（pass/fail 都入库）→ 返回 `{result, evidence, recommended_difficulty}` | checker + store |
| GET | /paths/{path_id}/progress | 进度派生：当前阶段/当前任务/已完成数/总数/百分比 | store.get_path + get_attempts |
| GET | /export | 全量嵌套导出 goals→paths→stages→tasks→attempts | store.export_all（本步新增） |

- store 本步新增两个小函数（同样 TDD）：`list_paths(goal_id=None)`、`export_all()`。
- main.py 同步补上 G2 遗留 TODO：lifespan 启动时 `store.init_db()`。

## 2. 精确语义

### 2.1 通用错误映射（API 层统一约定）

| 情况 | 状态码 |
|---|---|
| pydantic 校验失败（缺字段/类型错/超长） | 422 |
| 资源不存在（goal/path/task id 查无） | 404 |
| checker/planner 抛 ValueError（坏数据防御兜底） | 400，detail 原样带原因 |
| LLM client 抛异常（网络/API 错） | 502 |
| 未配置 DEEPSEEK_API_KEY | 503 |
| sqlite3.IntegrityError（外键缺失等，正常路径 404 已拦截） | 500 |

- 所有路由先查资源再操作，不依赖 DB 异常报 404；DB 异常仅作兜底。

### 2.2 client 注入（FastAPI dependency）

- `get_llm_client()` 工厂：读环境变量 `DEEPSEEK_API_KEY`（无 → 抛 503）；懒 import openai；`OpenAI(api_key=..., base_url="https://api.deepseek.com")`。
- 生成路由经 `Depends(get_llm_client)` 注入；测试用 `app.dependency_overrides` 挂 fake client，不碰真实网络。
- key 不硬编码、不进版本库（PROJECT_BRIEF 安全检查清单）。

### 2.3 各路由契约

- **POST /goals**：`statement` 非空 str（≤500）、`interests` list[str]（≤10 项，每项 ≤100，可空）；多余键忽略（与 planner 宽容策略一致）。返回 201 + get_goal 完整 dict。
- **POST /goals/{goal_id}/paths/generate**：goal 不存在 → 404；LLM 生成 → validate → create_path(goal_id, title, stages)（draft）→ 返回 201 + get_path(path_id) 完整树（未知键已在 validate 剔除）。本步只产 draft，不自动 active。
- **POST /paths/{path_id}/activate**：路径不存在 → 404；置 active（幂等，重复调用 200）。
- **POST /tasks/{task_id}/attempts**：按 task.kind 分流：
  - quiz：body `{answer: int|str}` → judge_quiz → result（用户输入坏 → fail，不崩）；
  - artifact：body `{checklist: [bool]}` → confirm_acceptance → result；
  - difficulty 快照 = task.difficulty（ADR 判分契约）；pass/fail 都 record_attempt（fail 喂难度推荐）；
  - 返回 `{result, evidence, recommended_difficulty}`：recommended = 入库后全量历史 recommend_difficulty（fail→降级 / 连 2 pass→升级 / 否则保持，N0/N3 夹取）。
- **GET /paths/{path_id}/progress**：只读派生，**不改 path status**（防魔法副作用）；任务 done ⇔ 存在任意 pass attempt；当前任务 = 按 stage/task 顺序第一个未完成；全部完成时 current=null、percent=100。
- **GET /export**：export_all() 嵌套 dump（attempts 按 task 挂载），免参。

## 3. 用例表（2.4 标准：正常 ≥3 + 攻击 ≥10，八大类每类 ≥1，组合 ≥2）

| 编号 | 类别 | 输入 | 预期 |
|---|---|---|---|
| T01 | 正常-最小 | POST /goals（interests 缺省）→ GET /goals 回读 | 201 + 列表含新 goal |
| T02 | 正常-典型 | POST generate（fake client 返回合法候选含未知键 + 代码块壳） | 201 draft 完整树，未知键已剔 |
| T03 | 正常-复杂 | quiz 文本答案大小写不敏感 pass；再答错一道 → fail；artifact 全勾 pass | result 正确；attempts 入库；recommended 随历史升降 |
| T04 | 正常-集成 | activate → GET /paths/{id} 为 active；GET progress 当前任务推进正确；GET /export 嵌套含 attempts | 全部一致 |
| T05 | 正常-store新增 | list_paths 按 goal 过滤 / export_all 空库与满库 | 结构正确 |
| A01 | 攻击-空数据 | statement 空白 / body 空对象 / checklist 空 | 422（statement 空白）；422（缺字段）；artifact 空 checklist → 400 或 fail（见 2.3）|
| A02 | 攻击-极值 | difficulty 0 任务答错 → recommended 0（N0 下限） | 0，不越界 |
| A03 | 攻击-越界 | 不存在 goal/path/task id；quiz answer 索引 99 | 404 / 404 / 404；fail 200 |
| A04 | 攻击-脏数据 | statement 前后空格 / answer "  Rag " | 保留往返；pass（checker 去空格） |
| A05 | 攻击-特殊字符 | statement 含 SQL 注入串 + emoji + 引号 | 201 后回读一致（参数化） |
| A06 | 攻击-异常格式 | body 非 JSON / answer 传 bool 或对象 | 422 |
| A07 | 攻击-缺失字段 | POST /goals 缺 statement / generate 前 goal 不存在 | 422 / 404 |
| A08 | 攻击-未知结构 | body 多余键 | 忽略（pydantic 默认），200 |
| A09 | 组合1 | 不存在的 goal 上 generate + 断言无 path 残留 | 404 且 store 无新增 path |
| A10 | 组合2 | quiz 坏数据（answer 越界 / options 空，直接写库绕过 planner）→ attempts | 400（ValueError 兜底），不 500 |
| A11 | 攻击-类型 | interests 非 list[str] / checklist 含非 bool | 422 |
| A12 | 攻击-超长 | statement 501 字 / interests 11 项 | 422 |
| A13 | 集成-攻击 | fake client 抛 RuntimeError / 返回坏 JSON / 无 key 工厂 | 502 / 400 / 503，进程不崩 |

## 4. 依赖与验证（实施第 1 步，先于写测试）

- FastAPI TestClient 依赖 httpx：`pip show httpx` 验证 venv 是否已有；缺则安装（沙箱下需 danger-full-access，PROJECT_BRIEF 已知坑）。
- 本步测试不依赖真实 key/网络：dependency_overrides 注入 fake client；无 key 分支只测 503 语义。

## 5. 执行步骤（TDD，严格顺序）

1. 验证 httpx（§4）→ 定 TestClient 可用性。
2. store TDD：`list_paths` + `export_all`（tests/test_store.py 追加用例，红→绿）。
3. 写 `tests/test_api.py`（上表落为 docstring + 测试代码，dependency_overrides 注入 fake client）→ 确认红。
4. 实现 `backend/main.py`：pydantic 模型 + lifespan init_db + get_llm_client 工厂 + 8 路由（改动 ≤250 行，无真实网络调用）。
5. 跑 `python -m pytest -q` → 全量绿（现有 56 + 新增）。
6. **可视化审核（用户规则）**：curl 冒烟——uvicorn 后台起服务，`curl /health`、`POST /goals`、`GET /export` 通；`POST generate` 无 key → 503 优雅不崩；输出原文贴用户审核。
7. ≤3 句解释 + 更新 `PROJECT_BRIEF.md` 轨道表（第 5 步 → 已完成，下一步第 6 步前端）。

### 出口条件
- test_api.py 全绿 + 全量绿；curl 冒烟输出经用户审核；AI 给出 ≤3 句解释；用户看懂并确认。

## 6. 决策记录（待用户确认）

- client 注入 = FastAPI dependency + dependency_overrides 测试注入；key 从环境变量读，openai 懒 import（无 key 不崩，路由级 503）。
- 错误映射固定表（2.1）：422/404/400/502/503/500 各司其职，detail 带原因。
- 进度只读派生、不自动改 path status（防魔法副作用）；"全部完成置 done" 触发方式留第 6 步定。
- attempts 一接口双模（quiz/artifact 按 task.kind 分流），pass/fail 都入库（fail 喂难度推荐）。
- pydantic 默认忽略多余键（与 planner 未知键宽容策略一致）；statement ≤500、interests ≤10×100。
- export 为全量嵌套 dump（免参 GET）；数据归属用户原则（PROJECT_BRIEF）。

## 7. 后续衔接

- validate 输出已与 store.create_path 签名对齐（G3-4 §7），本步直接串联，无需转换。
- 第 6 步前端三区 + fetch 联调：候选确认/修改 UI（渲染 → 用户改 → activate）。
- 第 7 步 dogfooding：真实 key 跑通「一句话目标 → 候选 → 确认 → 完成任务 → 进度 100%」全闭环。
