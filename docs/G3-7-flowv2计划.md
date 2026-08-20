# G3 第 7 步计划：流程 v2 实施（水平测试 + 增量生成 + chat 指导 + LLM 审核 + 沉淀）

- 日期：2026-08-20
- 状态：待开工令（用户明令：开工前禁止实现代码）
- 阶段：全模式 G3 小步实现（TDD）
- 输入：docs/flow-v2-design.md（**定稿**，D1-D6 已裁决）+ G3-6 已实现（98 绿）+ PROJECT_BRIEF 原则（候选确认 / LLM 不可信 / 不执行代码 / 先审后拍板）
- 说明：原「第 7 步 dogfooding」顺延到流程 v2 完成之后（真实 key 全闭环在终态做更有价值）

## 1. 实现对象（按步拆，每步一推送）

| 步 | 内容 | 出口 |
|---|---|---|
| A | schema + store：placement_tests / conversations 新表；stages + status/objective/summary；attempts + submission/file_name/file_path/llm_review/forced；store CRUD TDD | test_store 全绿 |
| B | planner 增量：generate/validate placement_test、overview、stage_tasks(n, 校准)、summarize_stage/all（mock TDD） | test_planner 全绿 |
| C | checker.review_artifact（LLM 审核建议制）+ backend/upload.py（白名单/大小/uuid/防穿越/摘录）TDD | test_checker + test_upload 全绿 |
| D | 路由串通 + artifact 判定升级（checklist → submission+LLM 审核+强行通过）+ 阶段状态机路由 + chat + 沉淀自动触发 TDD + curl 冒烟 | test_api 全绿 + 冒烟过 |
| E | 前端 v2：首屏三态 / 水平测试视图 / 计划审核 / 阶段轻确认 / chat 侧栏 / 上传 UI / 沉淀卡片 / 侧边栏阶段状态 + seed_demo v2 | K 走查（无 key 联调）用户审核 |

## 2. 精确语义

### 2.1 schema 增量（步 A；v0 未发布 → 直接重建 data/custom.db，不做迁移）

```sql
CREATE TABLE IF NOT EXISTS placement_tests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  goal_id INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
  questions TEXT NOT NULL,            -- 校验后的 [quiz]
  answers TEXT,                       -- 提交后 [int]，未提交 NULL
  created_at TEXT NOT NULL,
  graded_at TEXT
);
CREATE TABLE IF NOT EXISTS conversations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('user','assistant')),
  content TEXT NOT NULL,
  ts TEXT NOT NULL
);
-- stages 增列：status TEXT NOT NULL DEFAULT 'pending'
--   CHECK (status IN ('pending','review','learning','done'))
--   objective TEXT NOT NULL DEFAULT ''；summary TEXT（NULL=未沉淀）
-- attempts 增列：submission TEXT NOT NULL DEFAULT ''；file_name TEXT；file_path TEXT；
--   llm_review TEXT NOT NULL DEFAULT ''；forced INTEGER NOT NULL DEFAULT 0
```

阶段状态机：pending（仅标题+目标）→ review（任务已生成待轻确认）→ learning（确认落地）→ done（全 pass + 沉淀）。

### 2.2 planner 契约（步 B，client 注入式，复用现有 _quiz/_task/_stage 校验）

- `generate_placement_test(goal, interests, client)` → raw；`validate_placement_test` → `{questions: [quiz]}`，3-8 题，difficulty 覆盖 ≥2 档。
- `generate_overview(goal, interests, placement, client)` → `{title, stages: [{title, objective}]}`（1-10 阶段，无 tasks）。
- `generate_stage_tasks(ctx, client)` → `{tasks: [...]}`（复用 _stage 校验；ctx 含概览阶段、水平测试结果、前序阶段 pass 率 → 难度校准）。
- `summarize_stage(stage, attempts, client)` / `summarize_all(path, client)` → str（LLM 文本；失败调用方兜底占位，不阻塞主流程）。

### 2.3 checker + upload（步 C）

- `review_artifact(task, submission, file_excerpt, client)` → `{verdict: pass|needs_revision, review}`；LLM 异常 → 调用方 502；ValueError → 400。
- upload.py：`save_upload(filename, data)` → 扩展名白名单（.md .txt .py .js .ts .json .csv .log）· ≤1MB · uuid4 命名存 data/uploads/ · 原名仅返回值元数据；`read_excerpt(file_path, limit=20000)`；**上传目录不挂静态伺服**；路径不拼用户输入（防穿越）。

### 2.4 路由增量（步 D）

| 方法 | 路径 | 语义 |
|---|---|---|
| POST | /goals/{id}/placement/generate | 201 水平测试（无 key → 503） |
| POST | /placement/{id}/submit | body {answers:[int]} → 逐题 judge_quiz → 200 {correct,total,per} + 落库 |
| POST | /goals/{id}/plan/generate | 概览 + 阶段1任务（两次 LLM）→ 201 draft path（stages[0]=review，其余 pending）；可带 placement_id 校准 |
| POST | /paths/{id}/stages/{sid}/tasks/generate | pending/review 阶段（重）生成任务 → review |
| POST | /paths/{id}/stages/{sid}/confirm | 轻确认 review→learning |
| POST | /tasks/{id}/attempts | quiz 不变；artifact body {submission, forced?} + 可选 multipart 附件 → LLM 审核；forced=true → pass（证据含 LLM 意见+用户终裁） |
| GET/POST | /tasks/{id}/chat | 历史 / {content} → assistant 回复（持久化；只指导不改计划） |
| POST | /paths/{id}/stages/{sid}/summarize | 手动刷新沉淀（自动触发同入口） |
| POST | /paths/{id}/complete | 不变 + 自动 summarize_all（失败兜底占位） |

阶段 done 自动触发：attempt pass 后若该 stage 全 pass 且 summary 为空 → 后台同步 summarize_stage（LLM 失败 → 占位文案，不阻塞）。

**破坏性变更声明**：artifact 判定由 checklist 全勾升级为 submission+LLM 审核+用户终裁（D2）；acceptance 降级为展示用自评 rubric（并入审核 prompt）。G3-6 相关旧用例（test_api/test_checker 的 checklist 分支）在步 D 重写。

### 2.5 前端 v2（步 E，沿用 :root token 与三区布局）

首屏三态：active → 执行视图；draft → 计划审核；否则 → 新目标（[生成水平测试] + [跳过直接出计划] D1）。水平测试视图：quiz 列表单选 → submit → 出计划。计划审核：概览可编辑（title/objective、增删阶段）+ 阶段1任务轻确认。执行视图增量：侧边栏阶段状态符（pending ⋯ / review ！/ learning ● / done ✓）；阶段轻确认卡；artifact 提交卡（textarea + file input + [提交交付] + [强行通过]）；chat 侧栏（按 task 历史）；沉淀卡（stage.summary + [重新生成]）；done → 总沉淀 + 导出。

## 3. 用例要点（完整 2.4 表在各步测试 docstring 落，红→绿）

- A：新表 CRUD/级联/并发；stage 状态非法值拒；attempts 新列往返；placement answers 未交 NULL。
- B：placement 3-8 题越界拒；overview 缺 objective 拒；stage_tasks 校准输入坏历史不崩；summarize 坏 JSON 拒。
- C：白名单外扩展名拒；1MB+1 拒；uuid 落盘且原名不入库路径；摘录截断；review_artifact 双 verdict + 异常映射。
- D：全路由 200/400/404/409/502/503 分支；forced 证据链；阶段状态机非法跳转 409；chat 持久往返；沉淀失败兜底不阻塞；旧 checklist 语义移除。
- E：K 走查（含上传/chat/沉淀/跳过测试）+ XSS 复验 + 风格复验 K8。

## 4. 依赖与验证

- 无新 Python 依赖（multipart 用 starlette 自带 UploadFile；上传落盘用标准库）。
- data/uploads/ 入 .gitignore；重建 custom.db 后 seed_demo v2 造数（无 key 联调）。
- 步 A 开工即重启 uvicorn（schema 变更）。

## 5. 出口条件

全量 pytest 绿；K 走查用户可视化审核过；≤3 句解释；PROJECT_BRIEF 轨道表/文件地图更新；每步一推送。
