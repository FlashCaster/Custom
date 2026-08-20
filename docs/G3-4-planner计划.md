# G3 第 4 步计划：planner.py（DeepSeek 候选路径生成 + 严格校验 + draft）

- 日期：2026-08-20
- 状态：已完成（2026-08-20 用户终审通过：示例候选渲染无误）
- 阶段：全模式 G3 小步实现（TDD）
- 输入：PROJECT_BRIEF.md + docs/G1-方案.md §4 §5 §7 + backend/planner.py（G2 stub）+ backend/store.py（create_path 入参契约）+ backend/checker.py（quiz 结构契约）

## 1. 实现对象（沿用 G2 stub 已定签名，不新增）

```py
def generate_candidate_path(goal: str, interests: list[str], client) -> dict  # 返回 raw dict（未校验）
def validate_candidate_path(raw: dict) -> dict                               # 严格校验，非法全拒
```

## 2. 两函数精确语义

### 2.1 generate_candidate_path

- `goal` 非空 str、`interests` 为 list[str]（可为空），否则 `ValueError`（调用方责任）。
- 组装 prompt：system=课程设计师 + user=goal/interests/输出 schema 示例/规则；要求**仅输出 JSON、不套 markdown 代码块、中文**。
- 调用 `client`（OpenAI 兼容协议 `client.chat.completions.create`；DeepSeek 官方 SDK 有无待 §4 验证，两者同协议）：temperature 0.3、max_tokens 设上限（防超长）。
- 响应解析：取 content → 容错剥 markdown 代码块 → `json.loads` → 非 dict 抛 `ValueError`；**client 调用异常原样上抛**（重试/报错归调用方）。
- 返回 raw dict（不校验；校验是 validate 的职责）。

### 2.2 validate_candidate_path（G1 §5「坏 JSON/缺字段/难度越界/超长/非预期结构全拒」落地）

- `raw` 必须 dict，否则 `ValueError`。
- 结构：`{title: str非空, stages: [Stage]}`；stages 非空 list。
- Stage：dict；`title` 非空 str；`tasks` 非空 list。
- Task：dict；`kind ∈ {quiz, artifact}`；`title`/`brief` 非空 str；`difficulty` 非 bool int 且 0-3；`skills` 为 list[str]（可空）。
  - **quiz 任务**：`quiz` 必须 dict 且满足 checker 判分契约的坏数据规则——`q` 非空 str、`options` 非空 list、`answer` 非 bool int 且 `0 <= answer < len(options)`、`explanation` 可选 str。
  - **artifact 任务**：`acceptance` 必须**非空** list[str]（产出物任务无验收项=不可观测，违反完成判定原则，规划期即拦）。
- 超长全拒（上限表）：title/stage title/task title ≤80；brief ≤500；q ≤300；explanation ≤500；option ≤200；options 数 ≤6；acceptance/skills 每项 ≤200；stages ≤10；每 stage tasks ≤10。
- 未知键（顶层/Stage/Task 内）**丢弃不报错**（防 LLM 附加注释字段）；已知键类型/值违规、缺失必填、越界 → 全拒。
- **原子性**：整个候选整体通过或整体拒绝，不存在部分采纳。
- 通过后返回规范化 dict（剔除未知键，其余原样保留），可直接作 `store.create_path(goal_id, title, stages)` 的 stages 入参。

## 3. 用例表（2.4 标准：正常 ≥3 + 攻击 ≥10，八大类每类 ≥1，组合 ≥2）

| 编号 | 类别 | 输入 | 预期 |
|---|---|---|---|
| T01 | 正常-最小 | validate 单阶段单 quiz 任务 | 通过，结构一致 |
| T02 | 正常-典型 | validate 多阶段 quiz+artifact 混合 + 未知键 | 通过，未知键被丢弃 |
| T03 | 正常-复杂 | 难度 0/3 极值 + 引号/emoji 文本 | 通过 |
| T04 | 正常-集成 | generate mock client 返回合法 JSON（含代码块壳） | 剥壳后返回 dict |
| A01 | 空数据 | goal 空串 / stages=[] / raw 缺 title | ValueError |
| A02 | 极值 | difficulty -1/4/True | ValueError |
| A03 | 越界 | quiz.answer 越界 / options 空 | ValueError |
| A04 | 脏数据 | title 前后空格 | 通过（strip 后合法） |
| A05 | 特殊字符 | 选项含换行/引号/emoji | 通过 |
| A06 | 异常格式 | generate 返回非 JSON 文本 / JSON 是 list | ValueError |
| A07 | 缺失字段 | task 缺 difficulty / artifact acceptance 空 | ValueError |
| A08 | 未知结构 | 顶层多余键 + task kind 非法 | 丢键 / ValueError |
| A09 | 组合1 | stages 空 + title 空 | ValueError |
| A10 | 组合2 | 合法任务混 1 个非法任务（原子性） | 整体 ValueError |
| A11 | 类型 | title 是数字 / stages 是 dict / tasks 是 str | ValueError |
| A12 | 超长 | title 81 字 / option 201 字 | ValueError |
| A13 | 集成-攻击 | mock client 抛异常 | 原样上抛 |

## 4. 依赖与 SDK 验证（实施第 1 步，先于写测试）

- DeepSeek 官方是否有独立 Python SDK → `pip index versions deepseek` 验证官方源；无则用 openai SDK + `base_url=https://api.deepseek.com`（G1 §4 结论）。
- 本步实现与测试**不依赖真实 key/网络**：client 注入式设计（任何 OpenAI 兼容对象可替换），测试全 mock。
- 沙箱注意：pip 查询/安装需 danger-full-access（PROJECT_BRIEF 已知坑），残留临时目录清理同样。

## 5. 执行步骤（TDD，严格顺序）

1. SDK 验证（§4）→ 定 client 形态与 prompt 调用方式。
2. 写 `tests/test_planner.py`（上表落为 docstring + 测试代码，mock client）。
3. 跑 `python -m pytest tests/test_planner.py -q` → 确认**红**（`NotImplementedError`）。
4. 实现 `backend/planner.py` 两函数（改动 ≤120 行，无真实网络调用）。
5. 跑 `python -m pytest -q` → 全量**绿**（现有 38 + 新增）。
6. **可视化审核（用户规则）**：planner 为纯后端，以「示例候选路径渲染」作审核证据——用假 client 生成一条完整候选路径并格式化打印（缩进 JSON），先交用户过目。
7. ≤3 句解释 + 更新 `PROJECT_BRIEF.md` 轨道表（第 4 步 → 已完成，下一步第 5 步 API 路由）。

### 出口条件
- 第 4 步测试全绿；示例候选路径渲染经用户审核；AI 给出 ≤3 句解释；用户看懂并确认（**可视化编程：能预览的成果先审后拍板**）。

## 6. 决策记录（待用户确认）

- client 注入式 + 测试全 mock（不依赖 key/网络，key 不硬编码）。
- 未知键丢弃（宽容）而非全拒（防 LLM 注释字段炸路径）；已知键违规全拒。
- artifact 任务 acceptance 非空（完成判定可观测原则在规划期执行）。
- 长度上限表见 §2.2（防超长刷库/刷屏，LLM 输出不可信原则）。
- LLM 输出 = 候选：本步只产出 draft，用户确认后才落地（G1 §7，防幻觉）。

## 7. 后续衔接

- validate 输出直接 feed `store.create_path(goal_id, title, stages)`（stages 的 task 字段即 `_insert_task` 的 kwargs，签名级对齐，无需转换）。
- 第 5 步 API 路由串通 generate → validate → 存 draft → 返回候选给前端确认。
- 第 6 步前端把候选渲染给用户确认/修改 → 确认后 `set_path_status(active)`。
