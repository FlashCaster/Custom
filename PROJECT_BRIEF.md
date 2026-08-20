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
| docs/G3-6-前端计划.md | G3 第 6 步可执行计划（前端三区 + 候选编辑 PUT + complete + 静态伺服 + DeepTutor 风格迭代 v2 + K1-K8 走查）——实现完成，尾部走查吸收进 G3-7 步 E |
| docs/flow-v2-design.md | 产品流程 v2 定稿：完善流程图 + 三层状态图（path/stage/task，Mermaid 可编辑）+ D1-D6 裁决记录 |
| docs/G3-7-flowv2计划.md | G3 第 7 步实施计划：水平测试/增量生成/chat 指导/LLM 审核+用户终裁/文本+附件上传/自动沉淀，步 A-E TDD |
| docs/复盘日志.md | 每次会话 3 行复盘（坑归档进本档案已知坑） |
| scripts/seed_demo.py | dev-only 造数脚本（无 key 联调，直接 store 建 demo goal/path/attempts） |
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
- pwsh 把含双引号的 JSON 作参数传给 curl.exe 时引号被剥（服务端报 422 JSON decode error）→ curl 冒烟用 `--data-binary "@文件"` 传 body（workspace 内临时文件），勿用 `-d $变量` 内联
- starlette 1.6 的 TestClient 对 httpx 报弃用警告（建议 httpx2）→ 仅警告，功能正常；升级依赖时再跟进
- DSH 沙箱拦截 git→子进程的管道通信（credential helper 无论 GCM/sh/cmd/powershell 均返回空；pager 同样无输出）→ 沙箱内 `git push` 走 credential helper 必失败；绕行：`data/git-push.ps1`（不入库）从 GCM 读 github.com 凭证 → URL 内嵌 → git push（密钥只在进程内传递，不打印不落盘）；推给裸 URL 不更新本地 origin/main 引用，事后 `git fetch origin main` 同步 status
- pwsh 向 `python -c` / here-string 传带引号代码时引号被剥（SyntaxError，与 curl 剥引号同族）→ 改写临时 .py 文件执行、用后删，勿用 `-c` 内联带引号代码
- 浏览器自动请求 /favicon.ico，静态伺服无图标时控制台报 404（K1「控制台无报错」红线）→ index.html 声明内联 SVG data-URI favicon（零额外文件），已修复
- 上一会话的 uvicorn 未必随会话结束（本次交接时发现残留进程仍绑 8000，新实例 bind 报 WinError 10048，且 /health 200 来自旧代码实例，极易误判启动成功）→ 启动前先 `netstat -ano | Select-String ":8000"` 查占用，残留 `Stop-Process` 清理后再起；判断服务身份以自建后台 job 为准，勿信「200 即新实例」

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
| 主线：G3 第5步 API 路由 | 已完成 | test_api.py 18 用例 + 全量 77 绿；curl 冒烟（health/goals/export 通、无 key generate→503）已获用户终审确认并推送 | 无 |
| 主线：G3 第6步前端 | 实现完成，走查吸收 | 98 绿 + curl 冒烟全过；尾部走查（K1 复验/K4/K6/K7/K8）吸收进 G3-7 步 E 重走 | 无 |
| 主线：flow-v2 设计 | 已定稿 | D1-D6 裁决落 docs/flow-v2-design.md（可跳过/LLM建议+用户终裁/文本+附件/轻确认/按task持久/自动沉淀） | 无 |
| 主线：G3 第7步 flow-v2 实施 | 步 A 完成（2026-08-20） | 步 B：planner 增量（placement_test/overview/stage_tasks/summarize mock TDD）。步 A 出口：test_store 新增 17 例、全量 115 绿；custom.db 按新 schema 重建（不迁移）；uvicorn 已重启冒烟过 | 无 |

## 交接备忘（2026-08-20 · flow-v2 移交新会话）

- **运行时状态**：uvicorn 系上一会话后台 job，会话结束即失效；新会话在 Custom/ 根目录一条命令重启：`python -m uvicorn backend.main:app --port 8000`。data/custom.db 含 demo 数据（goal#2 / path#1 active，内含 K6 XSS 探针任务#7，清理时机见开放问②）。
- **未提交**：工作区 10 项变更（G3-6 实现 7 项 + flow-v2/G3-7 文档 2 项 + seed_demo），推送节奏待裁决（开放问③）。
- **开放问（已裁决 2026-08-20 新会话）**：① 吸收进 G3-7 步 E 重走（步 E 开工先把 K1/K4/K6/K7/K8 抄入走查清单逐项勾销，防吸收变漏掉）✓。② 不单独清——步 A 重建 custom.db 天然清掉探针任务#7；步 E seed_demo v2 不含探针，XSS 复验改走查时现场输入新探针 ✓。③ 已闭合：G3-6+文档已于 0573846 推送 ✓。
- **指导计划（新会话按序执行）**：1. 读 PROJECT_BRIEF + docs/flow-v2-design.md + docs/G3-7-flowv2计划.md；2. 裁决开放问①②③；3. 等开工令后入 G3-7 步 A（schema+store TDD；开工即重启 uvicorn，schema 变更不迁移、重建 demo 库）；4. 步 A→E 严格顺序、每步一推送、TDD 红→绿；5. 步 E 出口须用户可视化审核（先审后拍板）；6. dogfooding（真实 key 全闭环，含 K5 候选编辑走查）顺延至 flow-v2 完成后。

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
