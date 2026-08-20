# 产品流程 v2：流程图 + 状态图（可编辑 Mermaid）

- 日期：2026-08-20
- 状态：**定稿**（D1-D6 已裁决 2026-08-20：D1 可跳过 / D2 LLM 建议+用户终裁 / D3 文本+文件上传 / D4 轻确认 / D5 按 task 持久 / D6 自动沉淀）；实施计划见 docs/G3-7-flowv2计划.md
- 阶段：G1 级设计迭代（输入：用户手绘流程图 2026-08-20；底座：PROJECT_BRIEF + G1-方案 v2 + G3-6 已实现部分）
- 编辑方式：Mermaid 文本即源，粘到 mermaid.live / GitHub / Typora 可渲染；改图 = 改本文档

## 1. 完善后的流程图

相对手绘版的完善点：① 补「跳过水平测试」旁路（D1）；② 补阶段 n+1 任务的「用户确认」节点（原则：落地须确认，D4）；③ 判分菱形拆出 quiz/artifact 两支（artifact 走 LLM 审核 + 用户终裁，D2）；④ 补沉淀产出与导出节点；⑤ chat 求指导画为学习态的可选旁路（D5）。

```mermaid
flowchart TD
    A([用户启动页面]) --> B[/输入需求：一句话目标 + 兴趣点/]
    B --> C[LLM 生成水平测试<br/>按兴趣领域出 quiz 组]
    C --> D[用户答水平测试<br/>checker 自动判分]
    D --> E
    B -.->|跳过测试 D1| E

    E[LLM 据测试结果定制实践计划<br/>计划概览：m 个阶段标题+目标<br/>并生成阶段 1 任务]
    E --> F{用户审核}
    F -- 修改意见 --> E
    F -- 通过，初始化 n=1 --> G[侧边栏：计划概览栏 m 阶段<br/>主界面：阶段 1 任务栏]

    G --> H[用户确认阶段 1 任务 D4]
    H --> I

    I([进入阶段 n 实践学习<br/>可选：侧边栏看总概览/当前阶段指导<br/>可选：主界面 chat 求指导 D5])
    I --> J[阶段 n 详情页交付结果<br/>quiz：选选项 / artifact：文本描述+附件 D3]
    J --> K{结果判定}
    K -- quiz 自动判分 pass --> M
    K -- artifact 审核 pass --> M
    K -- quiz fail：展示解析，重试 --> I
    K -- artifact 需修改：LLM 意见<br/>用户可强行通过 D2 --> I

    M[阶段 n 完成：<br/>LLM 沉淀阶段产出，进度更新 D6]
    M --> N{n == m ?}
    N -- 否 --> N1[系统生成阶段 n+1 任务<br/>按阶段 n 表现 + 测试结果校准难度]
    N1 --> H2[用户轻确认阶段 n+1 任务 D4]
    H2 --> I
    N -- 是 --> O[LLM 沉淀总产出<br/>所有任务完成 → path done<br/>可导出]
    O --> P([结束])
```

## 2. 状态图（三层：path / stage / task）

### 2.1 Path 级

```mermaid
stateDiagram-v2
    [*] --> New: 输入一句话目标+兴趣点
    New --> Placement: 生成水平测试
    Placement --> Planning: 判分完成（结果作难度校准）
    New --> Planning: 跳过测试 D1
    Planning --> Planning: 修改意见 → LLM 改计划
    Planning --> Active: 审核通过（n=1，阶段1任务待确认）
    Active --> Done: n==m 且总产出沉淀
    Done --> [*]
```

### 2.2 Stage 级（Active 内，每阶段独立状态机）

```mermaid
stateDiagram-v2
    [*] --> TasksPending: 阶段实例化（仅标题+目标，来自概览）
    TasksPending --> TasksReview: 系统生成阶段 n 任务
    TasksReview --> TasksReview: 重生成 D4
    TasksReview --> Learning: 用户确认落地
    Learning --> Learning: fail/需修改 → 修正重交；chat 求指导
    Learning --> StageDone: 全部任务 pass + 阶段产出沉淀
    StageDone --> TasksPending: n=n+1
    StageDone --> [*]: n==m → path Done
```

### 2.3 Task 级

```mermaid
stateDiagram-v2
    [*] --> Pending
    Pending --> Judging: 交付结果
    Judging --> Passed: quiz 自动判分 pass / artifact 审核 pass
    Judging --> Failed: quiz fail
    Judging --> NeedsRevision: artifact LLM 修改意见 D2
    Judging --> Passed: artifact 用户强行通过 D2
    Failed --> Judging: 重试
    NeedsRevision --> Judging: 修正重交
    Passed --> [*]
```

注：若 D2 裁决「保留纯清单」，artifact 分支退化为现 confirm_acceptance（checklist 全勾 → Passed，无 NeedsRevision 态）。

## 3. 与现有实现（G3-6）的映射

| 流程 v2 节点 | 现有实现 | 变更 |
|---|---|---|
| 输入需求 | POST /goals + 新目标 hero 表单 | 复用 |
| LLM 生成水平测试 | — | 新增：planner.generate_placement_test + 路由 + 答题 UI |
| 水平测试判分 | checker.judge_quiz | 复用判分；新增整卷提交路由 |
| LLM 定制计划（概览+阶段1任务） | planner.generate_candidate_path（一次全树） | 重构：概览与阶段任务分离 |
| 用户审核循环 | 候选编辑 + PUT + activate | 复用（编辑范围视 D4） |
| 侧边栏概览栏 | 三态树 | 扩展：阶段状态（待生成/学习中/完成） |
| 阶段 n+1 任务生成 | 一次全生成 | 重构：增量生成 + 难度校准 |
| chat 求指导 | — | 新增：conversations 表 + 路由 + 主界面 chat 区 |
| quiz 自动判分 | checker + attempts | 复用 |
| artifact 判定 | confirm_acceptance 清单 | 视 D2/D3 重构（提交载体 + LLM 审核） |
| 阶段产出沉淀 | — | 新增：stages.summary + planner.summarize |
| 总产出 / done | complete + export | 扩展：总沉淀 + 导出 |

## 4. 裁决记录 D1-D6（2026-08-20 用户裁决）

| 编号 | 问题 | 裁决 |
|---|---|---|
| D1 | 水平测试可否跳过？ | **可跳过**（跳过 → 难度默认 N1 校准） |
| D2 | artifact 判定权归谁？ | **LLM 建议 + 用户终裁**（可「强行通过」，attempts 证据含双方意见） |
| D3 | artifact 提交载体？ | **文本描述 + 文件上传**（安全约束见实施计划：扩展名白名单/大小上限/uuid 命名/LLM 只读文本摘录） |
| D4 | 阶段 n+1 任务要不要用户确认？ | **轻确认**（列表 + [开始学习]/[重生成]，不逐字段编辑） |
| D5 | chat 求指导范围？ | **按 task 持久化**（conversations 表；只指导不改计划） |
| D6 | 沉淀产出触发方式？ | **自动沉淀**（阶段完成即 LLM 总结存 stage.summary，可刷新重生成） |

## 5. 后端结构要点（定稿；实施细节见 docs/G3-7-flowv2计划.md）

- 新表：`placement_tests`（goal_id, questions json, answers json, graded_at）｜`conversations`（task_id, role, content, ts）
- 列扩展：stages + `status`（pending/review/learning/done）+ `objective` + `summary`｜attempts + `submission`（文本载体）+ `file_name/file_path`（附件元数据）+ `llm_review` + `forced`
- planner 增：generate_placement_test / generate_overview / generate_stage_tasks(n, 校准) / summarize_stage / summarize_all
- checker 增：review_artifact（LLM 审核，D2 建议制）；judge_quiz 复用
- 上传安全红线：扩展名白名单（.md/.txt/.py/.js/.ts/.json/.csv/.log）· ≤1MB · uuid 命名存 data/uploads/ · 原名仅元数据 · LLM 只读前 2 万字符摘录 · 上传目录不静态伺服 · 防穿越
- 前端：首屏三态（水平测试/候选审核/新目标+跳过入口）· 阶段轻确认视图 · chat 侧栏 · 附件上传 UI · 沉淀卡片 · 侧边栏阶段状态化

裁决 D1-D6 → 更新本文档定稿 → 出实施计划（TDD 用例表+步骤）→ 开工令 → 动代码。
