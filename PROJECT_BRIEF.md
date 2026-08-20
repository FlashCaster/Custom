# 项目档案：Custom（原名 Truthy）

## 项目核心目标（项目存在的理由）
用 Custom 4 周后，用户能完成之前做不到的事：**从一个模糊的学习目标出发，得到一条明确的、有产出的、进度可见的学习路径，并完成路径上的第一个可验证项目**。

一句话：让"想学 X"变成"在学 X 的第 N 步，已完成 M 个可验证产出"。

v0 聚焦场景：**AI 工程师所需技能知识点**（LLM 基础 / 提示工程 / RAG / Agent / MCP / 评测 / AI 工程化——源自求职 JD 调研与《AI 编程工作流与 Prompt 模板》）；后续扩展数学、真实笔试等。

## 技术栈
- Python FastAPI 本地 Web 后端 + SQLite（无服务器、无云存储，数据全部在用户本地）
- 前端：原生 HTML/JS 单页（左侧任务导航、右上角进度、任务详情）
- LLM API：用户自带 key（OpenAI 兼容接口），**仅作路径/任务生成器**（候选 → 用户确认 → 落地）

## 文件地图（随项目更新）
| 路径 | 职责 |
|---|---|
| research.md | 研究文档（为什么做这件事） |
| PROJECT_BRIEF.md | 本档案（唯一事实来源） |
| ADR/ | 决策记录（一个决策一个文件） |
| docs/G1-方案.md | G1 方案 v2（数据结构 / 模块划分 / 测试策略 / 分步实施 / 安全设计） |
| docs/G3-3-checker计划.md | G3 第 3 步可执行计划（判分双模语义 + 2.4 用例表 + TDD 步骤） |
| docs/G3-4-planner计划.md | G3 第 4 步可执行计划（LLM 候选生成 + 严格校验 + mock 测试策略） |
| docs/G3-5-api路由计划.md | G3 第 5 步可执行计划（8 路由串通 + 错误映射 + curl 冒烟 + TestClient TDD） |
| docs/复盘日志.md | 每次会话 3 行复盘（坑归档进本档案已知坑） |
| backend/main.py | FastAPI 路由：goals/paths/tasks/attempts/export |
| backend/planner.py | DeepSeek 生成候选路径（含难度标注）→ 严格 JSON 校验 → draft |
| backend/checker.py | quiz 判分 + 难度推荐规则 + 验收清单确认 |
| backend/store.py | SQLite（sqlite3 标准库）CRUD，参数化 |
| frontend/index.html | 原生单页三区：左导航（当前置顶）\| 主区任务 \| 右上角进度条 |
| frontend/app.js | fetch API + 渲染（转义）+ 提交判定 |
| data/custom.db | SQLite 数据库（运行时生成） |

## 决策记录（ADR 索引）
| ADR 文件 | 决策一句话 | 日期 |
|---|---|---|
| ADR-2026-08-20-领域与形态.md | **已废弃**（被下方替代）：v0=DSH 插件判分训练场 | 2026-08-20 |
| ADR-2026-08-20-Custom方向确立.md | v0=本地 Web 个性化学习助手；执行层=任务引导+轻验证；模型=路径生成器+用户确认 | 2026-08-20 |
| ADR-2026-08-20-checker判分契约.md | quiz 答案=双模（索引 int+文本 str）；坏数据抛 ValueError、坏用户输入返回 fail | 2026-08-20 |

## 已知坑（踩过的坑 + 解法，AI 复述并遵守）
- LLM 生成的路径/任务/测试用例**不可信**（循环论证）→ 全部作为候选，用户确认后才落地；"所有选择透明"原则 = 防幻觉机制
- LLM 生成的 quiz 可能有错答案/歧义 → 用户确认后入库 + 定期人工抽查（≥20 道复核记录）
- 完成判定必须可观测，否则回到"学会了不可观测" → 轻验证：quiz 自动判分（达标过关）+ 产出物验收清单；**禁止纯人工打卡**
- **v0 不执行学生代码**（知识点场景无需求实现型判分）→ 判分沙箱后置，安全面大幅缩小
- 冷启动：首开产品是空的 → 一句话目标 + LLM 生成候选路径，首屏即有价值
- 数据归用户 → 提供数据导出；API key 本地存储（不进版本库、不硬编码）
- 内容权威来源已有 → 《AI 编程工作流与 Prompt 模板》= 技能点/任务类型的来源，不重复造轮子
- 本机 Python 3.13.1 无 ensurepip 内置轮子 → `venv` 引导 pip 必失败；用 `py -3.13 -m venv --without-pip` + get-pip.py 引导（或用 base pip `--target` 直接装进 venv）
- DSH 沙箱 workspace-write 拦截 pip/临时目录写入 → 依赖安装与清理临时目录需升级 danger-full-access；pip 残留临时目录可能被标记不可访问，pytest 用 `pytest.ini` 的 `testpaths=tests` 限定扫描范围
- DSH 沙箱会把 `tempfile.mkdtemp` 创建的目录标记为不可访问（scandir/写入/rmtree 均 PermissionError）→ pytest 的 `tmp_path` fixture 不可用；测试改用 workspace 内普通目录（`os.makedirs` + uuid 自建），并在 `pytest.ini` 加 `-p no:cacheprovider`（cacheprovider 写临时文件同样被拦）
- pwsh 跑 pytest/uvicorn 时控制台中文显示乱码（Windows 代码页）→ **纯显示问题**，不影响文件与判定；以测试结果数字为准，勿当编码 bug 排查

## 协作规则（用户已定，长期有效）

- **可视化编程 / 先审后拍板**：任何可可视化、可预览的成果（UI、渲染、示例输出、报告），在最终确认交付拍板前必须先交用户审核；纯后端逻辑（无 UI）以测试结果表 / 示例渲染为审核证据，同样先审后确认
- **每阶段一推送**：每完成一个阶段（G3 各步，用户确认出口后）立即 git 提交并推送到 origin/main；若当前项目没有 git 仓库则提醒用户先建仓库；禁止推送个人信息/密钥/运行时数据（.env、data/ 等，.gitignore 兜底，提交前必查）

## 当前状态（支持并行开发）
| 轨道 | 状态 | 下一步（具体一件事） | 阻塞 |
|---|---|---|---|
| 主线：G2 脚手架 | 已完成 | pytest 占位绿 + uvicorn /health ok | 无 |
| 主线：G3 第2步 store+schema | 已完成 | test_store.py 23 绿（CRUD+级联+并发） | 无 |
| 主线：G3 第3步 checker | 已完成 | test_checker.py 15 用例 + 全量 38 绿 | 无 |
| 主线：G1 方案设计 | 已完成 | 方案落盘 docs/G1-方案.md（v2） | 无 |
| 主线：G3 第4步 planner | 已完成 | test_planner.py 18 用例 + 全量 56 绿 + 示例候选渲染已终审；SDK 验证：PyPI deepseek 1.0.0 系第三方 deskpai 非官方 → openai SDK + base_url（client 注入式） | 无 |
| 主线：G3 第5步 API 路由 | 计划已落盘（待用户确认） | 按 docs/G3-5-api路由计划.md 写 test_api.py（TDD，TestClient + fake client） | 等用户确认计划 |
| 支线：前端骨架 | 未开始 | 三区布局 + fetch 联调（第 6 步） | 等 API 路由 |

## 完成定义（验收 + 安全双清单）

### 验收清单（功能可验证）
- [ ] 本地 Web 一条命令启动，SQLite 初始化，数据导出可用
- [ ] 初始化：一句话目标 + 兴趣点 → LLM 生成候选路径（阶段/任务/quiz）→ 用户确认/修改 → 落地
- [ ] 执行：左侧置顶显示当前阶段+任务；任务详情含学习目标/quiz/产出要求；右上角总进度实时更新，完成即推进下一任务
- [ ] 完成判定：quiz 自动判分（达标过关）+ 产出物验收清单，判定记录入库
- [ ] quiz 质量抽查：已确认 quiz ≥20 道，人工复核记录归档（错答案/歧义修正记录）
- [ ] dogfooding：用户本人从"一句话目标"走到"完成第一个项目"，全程记录
- [ ] G8 三层门禁通过，审查报告归档（= 简历面试证据包）

### 安全检查清单（对照《ai coding 安全问题》：AI 代码漏洞五大类）
- [ ] API key 本地存储：不进版本库、不硬编码（.env 或系统 keyring）
- [ ] LLM 输出 = 不可信输入：渲染转义防 XSS；路径/任务落地前必须用户确认
- [ ] 执行代码沙箱（若 v0 含跑测试）：隔离 + 超时 + 禁网 + 禁写宿主；路径校验防穿越
- [ ] 依赖：新增依赖均验证存在且来自官方源，无幻觉包
- [ ] 输入：SQLite 查询参数化；对外输入有验证
- [ ] Agent 面：不信任外部仓库/网页的配置文件与 MCP 工具描述
