// Custom 前端（G3-6）：零框架零构建单页。
// 状态机：boot → 有 active path → 执行视图；否则 → 新目标 → 生成候选 → 候选编辑 → 激活 → 执行 → done。
// XSS 红线：所有动态文本一律 textContent/createTextNode（el() 已封死），escapeHtml 备用并加载自检；禁止 innerHTML 拼接。
"use strict";

// ---------- XSS 防护 ----------

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}
// 加载自检（G3-6 §2.2）：转义函数必须覆盖五类字符
console.assert(
  escapeHtml('<img src=x onerror=alert(1)>') === "&lt;img src=x onerror=alert(1)&gt;"
  && escapeHtml('&"\'') === "&amp;&quot;&#39;",
  "escapeHtml 自检失败：转义函数不完整");

// ---------- fetch 封装 ----------

async function api(path, { method = "GET", body } = {}) {
  const opts = { method };
  if (body !== undefined) {
    opts.headers = { "Content-Type": "application/json" };
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) {
    throw { status: res.status, detail: (data && data.detail) || `${res.status} ${res.statusText}` };
  }
  return data;
}

// ---------- DOM 辅助（children 全部走 textNode，杜绝 innerHTML） ----------

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of [].concat(children)) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return node;
}

function svgIcon(paths, size = 15) {
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  for (const [k, v] of Object.entries({ width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": 1.5, "stroke-linecap": "round", "stroke-linejoin": "round" })) {
    svg.setAttribute(k, v);
  }
  for (const d of paths) {
    const p = document.createElementNS(NS, "path");
    p.setAttribute("d", d);
    svg.appendChild(p);
  }
  return svg;
}
const ICON_DOWNLOAD = ["M12 4v11", "M7.5 10.5 12 15l4.5-4.5", "M4.5 19.5h15"];

const $ = (id) => document.getElementById(id);

// ---------- 全局状态 ----------

const state = {
  view: "loading",   // loading | new-goal | edit | exec
  path: null,        // 当前 path 完整树（exec 视图含 attempts，来自 /export）
  draft: null,       // 候选编辑工作副本 {title, stages}
  dirty: false,      // 候选是否被改过（改过 → 先 PUT 再 activate）
  progress: null,    // {current_task_id, current_stage_id, completed, total, percent}
  selectedTaskId: null,
  lastResult: null,  // {taskId, result, evidence, recommended_difficulty}
};

function flatTasks(path) {
  return path.stages.flatMap((s) => s.tasks);
}
function taskDone(t) {
  return (t.attempts || []).some((a) => a.result === "pass");
}
function findStageOfTask(path, taskId) {
  for (const s of path.stages) if (s.tasks.some((t) => t.id === taskId)) return s;
  return null;
}

// ---------- boot：首屏分流 ----------

async function boot() {
  try {
    const dump = await api("/export");
    let active = null;
    for (const g of dump.goals) {
      for (const p of g.paths) if (p.status === "active") { active = p; break; }
      if (active) break;
    }
    if (active) {
      state.path = active;
      await enterExec();
    } else {
      showNewGoal();
    }
  } catch (e) {
    renderMain(el("div", { class: "container" }, [
      el("p", { class: "hint" }, [`加载失败：${e.detail || e}`]),
    ]));
  }
}

// ---------- 视图 1：新目标 ----------

function showNewGoal(hintMsg = "") {
  state.view = "new-goal";
  setTopbar("新的学习目标", false);
  renderSidebarEmpty("暂无进行中的学习路径");
  const hint = el("span", { class: hintMsg ? "hint" : "hint info" },
    [hintMsg || "一句话目标 + 兴趣点，生成个性化学习路径"]);
  const goalInput = el("textarea", { placeholder: "例如：想从零学会 RAG，最终做出一个能用的检索增强问答小应用", rows: 2 });
  const interestsInput = el("input", { class: "interests", placeholder: "兴趣点（逗号分隔，可选）：检索、向量数据库、LangChain…" });
  const genBtn = el("button", { class: "btn-primary" }, ["生成候选路径"]);
  genBtn.addEventListener("click", () => onGenerate(goalInput, interestsInput, genBtn, hint));

  renderMain(el("div", { class: "container" }, [
    el("div", { class: "hero" }, [
      el("h2", { class: "hero-title" }, ["你想学什么？"]),
      el("p", { class: "hero-sub" }, ["从一个模糊的目标出发，得到一条进度可见、产出可验证的学习路径。"]),
      el("div", { class: "input-card" }, [
        goalInput, interestsInput,
        el("div", { class: "input-actions" }, [hint, genBtn]),
      ]),
    ]),
  ]));
}

async function onGenerate(goalInput, interestsInput, btn, hint) {
  const statement = goalInput.value.trim();
  if (!statement) {
    hint.className = "hint";
    hint.textContent = "请先输入一句话学习目标";
    return;
  }
  const interests = interestsInput.value.split(/[,，]/).map((s) => s.trim()).filter(Boolean);
  btn.disabled = true;
  btn.textContent = "正在生成…";
  hint.className = "hint info";
  hint.textContent = "LLM 正在设计路径，请稍候（约 10-30 秒）";
  try {
    const goal = await api("/goals", { method: "POST", body: { statement, interests } });
    const path = await api(`/goals/${goal.id}/paths/generate`, { method: "POST" });
    enterEdit(path);
  } catch (e) {
    hint.className = "hint";
    hint.textContent = e.status === 503
      ? "未配置 DEEPSEEK_API_KEY：请设置环境变量后重启服务，再生成"
      : e.status === 502 ? "LLM 调用失败，请稍后重试" : `生成失败：${e.detail || e}`;
    btn.disabled = false;
    btn.textContent = "生成候选路径";
  }
}

// ---------- 视图 2：候选编辑 ----------

function enterEdit(path) {
  state.view = "edit";
  state.path = path;
  state.draft = JSON.parse(JSON.stringify({ title: path.title, stages: path.stages }));
  state.dirty = false;
  setTopbar("修改候选路径", false);
  renderSidebarEmpty("候选路径编辑中，确认后激活");
  renderEditView();
}

function renderEditView(hintMsg = "") {
  const hint = el("span", { class: hintMsg ? "hint" : "hint info" }, [hintMsg || ""]);

  const titleInput = el("input", { class: "text-input", value: state.draft.title });
  titleInput.addEventListener("input", () => { state.draft.title = titleInput.value; state.dirty = true; });

  const stageCards = state.draft.stages.map((stage, si) => renderStageEditor(stage, si));
  const activateBtn = el("button", { class: "btn-primary" }, ["确认并激活"]);
  activateBtn.addEventListener("click", () => onActivate(activateBtn, hint));

  renderMain(el("div", { class: "container" }, [
    el("h2", { class: "section-title" }, ["审阅并修改候选路径"]),
    el("p", { class: "edit-tip" }, ["候选由 LLM 生成、未经确认。可修改标题/目标/题目/选项/验收清单，可删除任务或整个阶段；点击「确认并激活」后才落地。"]),
    el("div", { class: "card" }, [
      el("label", { class: "field-label" }, ["路径标题"]),
      titleInput,
    ]),
    ...stageCards,
    el("div", { class: "card" }, [
      el("div", { class: "input-actions" }, [hint, activateBtn]),
    ]),
  ]));
}

function renderStageEditor(stage, si) {
  const stageTitle = el("input", { class: "text-input grow", value: stage.title });
  stageTitle.addEventListener("input", () => { stage.title = stageTitle.value; state.dirty = true; });
  const delStage = el("button", { class: "ghost-btn danger" }, ["删除阶段"]);
  delStage.addEventListener("click", () => {
    state.draft.stages.splice(si, 1);
    state.dirty = true;
    renderEditView();
  });

  const taskCards = stage.tasks.map((task, ti) => renderTaskEditor(stage, task, si, ti));
  return el("div", { class: "card section-gap" }, [
    el("div", { class: "card-head" }, [
      el("span", { class: "badge dim" }, [`阶段 ${si + 1}`]),
      stageTitle, delStage,
    ]),
    ...taskCards,
  ]);
}

function renderTaskEditor(stage, task, si, ti) {
  const titleInput = el("input", { class: "text-input grow", value: task.title });
  titleInput.addEventListener("input", () => { task.title = titleInput.value; state.dirty = true; });
  const delTask = el("button", { class: "ghost-btn danger" }, ["删除任务"]);
  delTask.addEventListener("click", () => {
    stage.tasks.splice(ti, 1);
    state.dirty = true;
    renderEditView();
  });
  const briefInput = el("input", { class: "text-input", value: task.brief });
  briefInput.addEventListener("input", () => { task.brief = briefInput.value; state.dirty = true; });

  const body = [];
  if (task.kind === "quiz") {
    const qInput = el("input", { class: "text-input", value: task.quiz.q });
    qInput.addEventListener("input", () => { task.quiz.q = qInput.value; state.dirty = true; });
    body.push(el("label", { class: "field-label" }, ["题目"]), qInput);
    body.push(el("label", { class: "field-label" }, ["选项"]));
    task.quiz.options.forEach((opt, oi) => {
      const optInput = el("input", { class: "text-input", value: opt, style: "margin-top:6px" });
      optInput.addEventListener("input", () => { task.quiz.options[oi] = optInput.value; state.dirty = true; });
      body.push(optInput);
    });
  } else {
    body.push(el("label", { class: "field-label" }, ["验收清单"]));
    task.acceptance.forEach((item, ii) => {
      const itemInput = el("input", { class: "text-input", value: item, style: "margin-top:6px" });
      itemInput.addEventListener("input", () => { task.acceptance[ii] = itemInput.value; state.dirty = true; });
      body.push(itemInput);
    });
  }
  const diffText = `难度 ${task.difficulty}${(task.skills && task.skills.length) ? " · 技能：" + task.skills.join("、") : ""}`;
  return el("div", { class: "card section-gap" }, [
    el("div", { class: "card-head" }, [
      el("span", { class: "badge" }, [task.kind === "quiz" ? "quiz 测验" : "artifact 产出"]),
      titleInput, delTask,
    ]),
    el("label", { class: "field-label" }, ["学习目标"]),
    briefInput,
    ...body,
    el("div", { class: "meta-line" }, [diffText]),
  ]);
}

function draftPayload() {
  // PUT 载荷：只带契约字段（id/stage_id 等读库冗余键不带，服务端 validate 只认这些）
  return {
    title: state.draft.title,
    stages: state.draft.stages.map((s) => ({
      title: s.title,
      tasks: s.tasks.map((t) => {
        const out = { kind: t.kind, title: t.title, brief: t.brief, difficulty: t.difficulty };
        if (t.skills && t.skills.length) out.skills = t.skills;
        if (t.kind === "quiz") {
          out.quiz = { q: t.quiz.q, options: t.quiz.options, answer: t.quiz.answer };
          if (t.quiz.explanation != null) out.quiz.explanation = t.quiz.explanation;
        } else {
          out.acceptance = t.acceptance;
        }
        return out;
      }),
    })),
  };
}

function validateDraft() {
  // 客户端预检（服务端 planner.validate 仍是最终裁决）：非空项逐一检查
  const d = state.draft;
  if (!d.title.trim()) return "路径标题不能为空";
  if (!d.stages.length) return "至少保留一个阶段（当前已全部删除，无法激活）";
  for (let si = 0; si < d.stages.length; si++) {
    const s = d.stages[si];
    if (!s.title.trim()) return `阶段 ${si + 1} 标题不能为空`;
    if (!s.tasks.length) return `阶段 ${si + 1}「${s.title}」没有任务，请删除该阶段或补充任务`;
    for (const t of s.tasks) {
      if (!t.title.trim()) return `阶段 ${si + 1} 存在标题为空的任务`;
      if (!t.brief.trim()) return `任务「${t.title || "(无标题)"}」的学习目标不能为空`;
      if (t.kind === "quiz") {
        if (!t.quiz.q.trim()) return `任务「${t.title}」的题目不能为空`;
        if (!t.quiz.options.length || t.quiz.options.some((o) => !o.trim())) {
          return `任务「${t.title}」的选项不能为空`;
        }
      } else if (!t.acceptance.length || t.acceptance.some((a) => !a.trim())) {
        return `任务「${t.title}」的验收清单不能为空`;
      }
    }
  }
  return null;
}

async function onActivate(btn, hint) {
  const problem = validateDraft();
  if (problem) {
    hint.className = "hint";
    hint.textContent = problem;
    return;
  }
  btn.disabled = true;
  btn.textContent = "落地中…";
  try {
    if (state.dirty) {
      await api(`/paths/${state.path.id}`, { method: "PUT", body: draftPayload() });
    }
    await api(`/paths/${state.path.id}/activate`, { method: "POST" });
    await enterExec();
  } catch (e) {
    hint.className = "hint";
    hint.textContent = `激活失败：${e.detail || e}`;
    btn.disabled = false;
    btn.textContent = "确认并激活";
  }
}

// ---------- 视图 3：执行 ----------

async function enterExec() {
  state.view = "exec";
  state.lastResult = null;
  await refreshExec();
}

async function refreshExec() {
  const [dump, prog] = await Promise.all([
    api("/export"),
    api(`/paths/${state.path.id}/progress`),
  ]);
  const path = dump.goals.flatMap((g) => g.paths).find((p) => p.id === state.path.id);
  if (!path) throw { detail: "路径不存在（可能已被删除）" };
  state.path = path;
  state.progress = prog;
  const tasks = flatTasks(path);
  if (!state.selectedTaskId || !tasks.some((t) => t.id === state.selectedTaskId)) {
    state.selectedTaskId = prog.current_task_id ?? (tasks[0] ? tasks[0].id : null);
  }
  setTopbar(path.title, true);
  renderProgress();
  renderSidebarTree();
  renderTaskView();
}

function setTopbar(title, showProgress) {
  $("topbar-title").textContent = title;
  $("progress").hidden = !showProgress;
}

function renderProgress() {
  const p = state.progress;
  $("progress-fill").style.width = `${p.percent}%`;
  const stage = p.current_stage_id != null
    ? state.path.stages.find((s) => s.id === p.current_stage_id) : null;
  $("progress-text").textContent = stage
    ? `${p.percent}% · ${stage.title}`
    : p.percent === 100 ? "100% · 全部完成" : `${p.percent}%`;
}

function renderSidebarEmpty(msg) {
  $("nav-tree").replaceChildren(el("div", { class: "empty-state" }, [msg]));
}

function renderSidebarTree() {
  const nav = $("nav-tree");
  const path = state.path;
  const prog = state.progress;
  const nodes = [];

  nodes.push(el("div", { class: "nav-group-title" }, ["当前"]));
  if (prog.current_task_id != null) {
    const t = flatTasks(path).find((x) => x.id === prog.current_task_id);
    if (t) {
      nodes.push(navItem(t, { current: true }));
    }
  } else {
    nodes.push(el("div", { class: "empty-state" },
      [prog.percent === 100 ? "全部任务已完成 ✓" : "暂无任务"]));
  }

  nodes.push(el("div", { class: "nav-group-title" }, ["全部阶段"]));
  path.stages.forEach((s, si) => {
    nodes.push(el("div", { class: "nav-group-title" }, [`阶段 ${si + 1}`]));
    for (const t of s.tasks) nodes.push(navItem(t, {}));
  });
  nav.replaceChildren(...nodes);

  function navItem(t, { current = false }) {
    const classes = ["nav-item"];
    if (current) classes.push("current");
    if (t.id === state.selectedTaskId) classes.push("selected");
    const mark = taskDone(t)
      ? el("span", { class: "nav-check" }, ["✓"])
      : current ? el("span", { class: "nav-dot" }) : el("span", { class: "nav-dot", style: "visibility:hidden" });
    const item = el("div", { class: classes.join(" ") }, [mark, el("span", { class: "t" }, [t.title])]);
    item.addEventListener("click", () => {
      state.selectedTaskId = t.id;
      renderSidebarTree();
      renderTaskView();
    });
    return item;
  }
}

function renderTaskView() {
  const path = state.path;
  const tasks = flatTasks(path);
  const main = el("div", { class: "container" });

  if (path.status === "done") {
    main.append(el("div", { class: "done-banner" }, [
      el("div", { class: "big" }, ["🎓 学习路径已完成"]),
      el("div", { class: "sub" }, ["可点击右上角「导出」备份全部学习记录（goals→paths→tasks→attempts）"]),
    ]));
  }

  const task = tasks.find((t) => t.id === state.selectedTaskId);
  if (!task) {
    main.append(el("div", { class: "card" }, [el("p", {}, ["这条路径还没有任务。"])]));
    renderMain(main);
    return;
  }
  const stage = findStageOfTask(path, task.id);
  const si = path.stages.indexOf(stage);

  const head = [
    el("p", { class: "crumb" }, [`阶段 ${si + 1} · ${stage.title}`]),
    el("div", { class: "card-head" }, [
      el("span", { class: "badge" }, [task.kind === "quiz" ? "quiz 测验" : "artifact 产出"]),
      el("span", { class: "badge dim" }, [`难度 ${task.difficulty}`]),
      ...(task.skills || []).map((s) => el("span", { class: "badge dim" }, [s])),
    ]),
    el("h2", { class: "section-title", style: "margin-top:14px" }, [task.title]),
  ];
  if (task.brief) head.push(el("p", { class: "task-brief" }, [task.brief]));

  if (task.kind === "quiz") head.push(...renderQuiz(task));
  else head.push(...renderArtifact(task));

  const r = state.lastResult;
  if (r && r.taskId === task.id) {
    main.append(el("div", { class: `result ${r.result}` }, [
      el("div", { class: "verdict" }, [r.result === "pass" ? "✓ 通过" : "✗ 未通过"]),
      el("div", { class: "evidence" }, [r.evidence || ""]),
      el("div", { class: "recommend" }, [`推荐下次难度：${r.recommended_difficulty}`]),
    ]));
  }

  main.append(el("div", { class: "card" }, head));

  // 完成态：percent==100 且未 done → [标记完成]
  if (path.status !== "done" && state.progress.percent === 100) {
    const btn = el("button", { class: "btn-primary" }, ["标记完成"]);
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      btn.textContent = "提交中…";
      try {
        await api(`/paths/${path.id}/complete`, { method: "POST" });
        await refreshExec();
      } catch (e) {
        btn.disabled = false;
        btn.textContent = "标记完成";
        window.alert(`标记失败：${e.detail || e}`);
      }
    });
    main.append(el("div", { class: "card section-gap", style: "text-align:center" }, [
      el("p", { style: "margin:0 0 12px" }, ["所有任务已完成，进度 100%"]),
      btn,
    ]));
  }
  renderMain(main);
}

function renderQuiz(task) {
  const wrap = el("div");
  wrap.append(el("div", { class: "quiz-q" }, [task.quiz.q]));
  const optRows = task.quiz.options.map((opt, oi) => {
    const radio = el("input", { type: "radio", name: `quiz-${task.id}` });
    const row = el("label", { class: "opt-row" }, [
      radio, el("span", { class: "opt-dot" }), el("span", {}, [opt]),
    ]);
    radio.addEventListener("change", () => {
      optRows.forEach((r) => r.classList.remove("selected"));
      row.classList.add("selected");
    });
    return row;
  });
  wrap.append(...optRows);

  const hint = el("span", { class: "hint" });
  const btn = el("button", { class: "btn-primary" }, ["提交答案"]);
  btn.addEventListener("click", async () => {
    const idx = optRows.findIndex((r) => r.querySelector("input").checked);
    if (idx < 0) { hint.textContent = "请先选择一个选项"; return; }
    hint.textContent = "";
    btn.disabled = true;
    try {
      const r = await api(`/tasks/${task.id}/attempts`, { method: "POST", body: { answer: idx } });
      state.lastResult = { taskId: task.id, ...r };
      await refreshExec();
    } catch (e) {
      hint.textContent = `提交失败：${e.detail || e}`;
      btn.disabled = false;
    }
  });
  wrap.append(el("div", { class: "submit-line" }, [btn, hint]));
  return [wrap];
}

function renderArtifact(task) {
  const wrap = el("div");
  wrap.append(el("label", { class: "field-label" }, ["验收清单（全部完成后勾选提交）"]));
  const rows = task.acceptance.map((item) => {
    const box = el("input", { type: "checkbox" });
    const row = el("label", { class: "check-row" }, [
      box, el("span", { class: "check-box" }), el("span", {}, [item]),
    ]);
    box.addEventListener("change", () => row.classList.toggle("selected", box.checked));
    return row;
  });
  wrap.append(...rows);

  const hint = el("span", { class: "hint" });
  const btn = el("button", { class: "btn-primary" }, ["提交验收"]);
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    try {
      const checklist = rows.map((r) => r.querySelector("input").checked);
      const r = await api(`/tasks/${task.id}/attempts`, { method: "POST", body: { checklist } });
      state.lastResult = { taskId: task.id, ...r };
      await refreshExec();
    } catch (e) {
      hint.textContent = `提交失败：${e.detail || e}`;
      btn.disabled = false;
    }
  });
  wrap.append(el("div", { class: "submit-line" }, [btn, hint]));
  return [wrap];
}

// ---------- 通用渲染 / 导出 ----------

function renderMain(node) {
  $("main").replaceChildren(node);
}

async function onExport() {
  try {
    const dump = await api("/export");
    const blob = new Blob([JSON.stringify(dump, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "custom-export.json";
    a.click();
    URL.revokeObjectURL(a.href);
  } catch (e) {
    window.alert(`导出失败：${e.detail || e}`);
  }
}

// ---------- 启动 ----------

document.addEventListener("DOMContentLoaded", () => {
  $("btn-export").addEventListener("click", onExport);
  $("btn-export-side").addEventListener("click", onExport);
  $("btn-export").prepend(svgIcon(ICON_DOWNLOAD));
  $("btn-export-side").prepend(svgIcon(ICON_DOWNLOAD));
  boot();
});
