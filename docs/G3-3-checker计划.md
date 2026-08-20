# G3 第 3 步计划：checker.py（quiz 判分 + 难度推荐 + 验收清单确认）

- 日期：2026-08-20
- 状态：已完成（15 用例绿 + 全量 38 绿；复盘见 docs/复盘日志.md）
- 阶段：全模式 G3 小步实现（TDD）
- 输入：PROJECT_BRIEF.md + docs/G1-方案.md §2 §5 + backend/checker.py（G2 stub）

## 1. 实现对象（沿用 G2 stub 已定签名，不新增）

```py
def judge_quiz(task: dict, answer) -> dict:            # {result: "pass"|"fail", explanation}
def recommend_difficulty(history: list[dict]) -> int   # 返回 0-3
def confirm_acceptance(task: dict, checklist: list[bool]) -> bool
```

## 2. 三函数精确语义

### 2.1 judge_quiz（quiz 判分）

- 取 `task["quiz"]`；非 dict → `ValueError`（坏数据）。
- 校验 **quiz 数据**（属坏数据，抛 `ValueError`，本应由 planner 第 4 步拦截，此处防御性兜底）：
  - `options` 为非空 list
  - `answer` 为非 bool 的 int 且 `0 <= answer < len(options)`
- 用户答案 `answer` 匹配（**双模：索引 int + 文本 str**）：
  1. `None` 或空白字符串（含纯空格）→ **fail**
  2. `int`（非 bool）→ 当**索引**与 `quiz.answer` 比较；越界索引 → **fail**
  3. 纯数字串（如 `"0"`）→ 当索引
  4. 其它字符串 → **大小写不敏感 + 去首尾空格**，与正确选项文本 `options[answer]` 匹配
  5. 其它类型（bool / list / dict 等）→ **fail**（不崩溃）
- 返回 `{"result": "pass"|"fail", "explanation": quiz.get("explanation", "")}`。

### 2.2 recommend_difficulty（难度推荐，G1 §2 规则）

- 逐条校验 history 元素（须为 dict；`result ∈ {pass,fail}`；`difficulty` 为非 bool 的 int 且 `0-3`），否则 `ValueError`。
- 规则（`current` = 最近一条的 difficulty）：
  1. 空历史 → **1**
  2. 最近一条 `fail` → `max(0, current - 1)`
  3. 最近两条同难度且都 `pass` → `min(3, current + 1)`
  4. 否则 → 保持 `current`

### 2.3 confirm_acceptance（验收清单确认）

- `task["acceptance"]` 须为非空 list（否则 `ValueError`，产出物任务无验收项=不可观测，违反完成判定原则）。
- `checklist` 须为 bool list 且长度 == len(acceptance)（否则 `ValueError`）。
- 返回 `all(checklist)`（全部勾选才 True）。

## 3. 用例表（2.4 标准：正常 ≥3 + 攻击 ≥10，八大类每类 ≥1，组合 ≥2）

| 编号 | 类别 | 输入 | 预期 |
|---|---|---|---|
| T01 | 正常-最小 | judge 索引答对（answer=0） | pass |
| T02 | 正常-典型 | judge 文本答对（`"rag"` vs `"RAG"`） | pass |
| T03 | 正常-复杂 | recommend 连续 2 pass 升级；confirm 全勾 | 升级 / True |
| A01 | 空数据 | judge 空白 answer / recommend 空历史 / confirm 空 acceptance | fail / 1 / ValueError |
| A02 | 极值 | recommend fail@0 → N0 下限 / 2pass@3 → N3 上限 | 0 / 3 |
| A03 | 越界 answer(用户) | judge 索引 99 | fail |
| A04 | 越界 answer(数据) | quiz.answer=5（仅 3 选项） | ValueError |
| A05 | 空选项 | options=[] | ValueError |
| A06 | 脏数据 | 文本答案 `"  Rag "` 前后空格 | pass（去空格） |
| A07 | 特殊字符 | 选项含引号/emoji，文本匹配 | pass |
| A08 | 异常格式 | 数字串 `"0"` 当索引 / result=`"maybe"` | 正确判 / ValueError |
| A09 | 缺失字段 | task 缺 quiz / history 项缺 difficulty | ValueError |
| A10 | 组合1 | 越界 answer + 空选项 | ValueError |
| A11 | 组合2 | 长 history 混合 fail+pass 只取最近 | 正确值 |
| A12 | 类型 | bool/list 当 answer / checklist 含非 bool | fail / ValueError |

## 4. 执行步骤（TDD，严格顺序）

1. 写 `tests/test_checker.py`（上表落为 docstring + 测试代码）。
2. 运行 `python -m pytest tests/test_checker.py -q` → 确认 **红**（`NotImplementedError`）。
3. 实现 `backend/checker.py` 三个函数（改动 ≤ 100 行，无新增依赖，SQL 无关）。
4. 运行 `python -m pytest -q` → 全量 **绿**（现有 23 用例 + 新增用例）。
5. ≤3 句解释（改了什么/为什么/需确认什么）+ 更新 `PROJECT_BRIEF.md` 轨道表（第 3 步 → 已完成，下一步第 4 步 planner）。

### 出口条件
- 第 3 步测试全绿；AI 给出 ≤3 句解释；用户看懂并确认（可视化审核：本步为纯后端逻辑，无可预览 UI，以测试结果表为审核证据）。

## 5. 决策记录（本次会话已确认）

- **quiz 答案形态 = 双模**：`answer` 既可是**索引 int**（含纯数字串），也可是**文本 str**（大小写不敏感、去首尾空格匹配正确选项文本）。依据：G2 stub 签名 `answer: object` + G1 §5 边界清单「空白/大小写/越界 answer/空选项」。
- **judge_quiz 对「坏数据」抛 ValueError、对「坏用户输入」返回 fail** 的二分：坏数据（空选项/answer 越界/quiz 非 dict）是系统缺陷，应由 planner 拦截，此处兜底报错；坏用户输入（空白/越界索引/错文本）是正常交互，返回 fail 不崩。

## 6. 后续衔接

- store.get_attempts 返回的 dict（含 `difficulty`/`result`）直接可作为 recommend_difficulty 的 history 入参，无需转换。
- judge_quiz 返回值 `{result, explanation}` 供前端渲染「对/错 + 解析」；前端提交形态需与双模约定一致（索引 int 或文本 str）。
