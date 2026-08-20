"""DeepSeek 候选路径生成器：目标+兴趣点 → 候选路径（阶段/任务/quiz）→ 严格 JSON 校验 → draft。

G3 第 4 步（TDD，client 注入式，测试全 mock）。generate 调 client.chat.completions.create（OpenAI
兼容协议）返回 raw dict（未校验），client 异常原样上抛、解析失败抛 ValueError；validate 坏 JSON/
缺字段/难度越界/超长/非预期结构全拒（原子性），通过后返回规范化 dict（剔未知键，其余原样保留），可直接作 store.create_path 的 stages 入参。SDK 结论（§4）：PyPI deepseek 1.0.0 系第三方 deskpai 非官方 → 用 openai SDK + base_url=https://api.deepseek.com（model=deepseek-chat），不 import SDK。"""
from __future__ import annotations
import json
DEFAULT_MODEL = "deepseek-chat"
MAX_TOKENS = 6000  # 输出上限（防超长刷屏；超出规模的候选本就被超长校验拒绝）
LIM_TITLE, LIM_BRIEF, LIM_Q, LIM_EXPL, LIM_OPT, LIM_ITEM = 80, 500, 300, 500, 200, 200
MAX_STAGES, MAX_TASKS, MAX_OPTIONS = 10, 10, 6
_SYSTEM = (
    "你是一位资深 AI 工程师课程设计师。根据用户的学习目标与兴趣点，设计一条循序渐进的学习路径："
    "若干阶段（stage），每阶段若干任务（task）。任务分两类：quiz（单选题，考察知识点）与 artifact"
    "（产出物任务，给验收清单 acceptance）。每任务标注 difficulty（0=入门 1=基础 2=进阶 3=挑战）。"
    "只输出 JSON（不要 markdown 代码块、不要任何解释），全部使用中文。")
_EXAMPLE = {
    "title": "AI 工程师入门路径",
    "stages": [{
        "title": "阶段一：提示工程基础",
        "tasks": [
            {"kind": "quiz", "title": "什么是 Prompt", "brief": "理解提示工程基本概念", "difficulty": 1,
             "skills": ["提示工程"], "quiz": {"q": "以下哪项最能描述 Prompt？",
             "options": ["给模型的输入指令", "模型参数", "训练数据"], "answer": 0,
             "explanation": "Prompt 是给模型的输入指令。"}},
            {"kind": "artifact", "title": "写一份提示词清单", "brief": "产出可复用清单", "difficulty": 2,
             "skills": ["提示工程"], "acceptance": ["至少 5 条", "每条含使用场景"]}],
    }],
}

def _strip_fence(text: str) -> str:
    """容错剥离 markdown 代码块壳（```json ... ```）。"""
    text = text.strip()
    if text.startswith("```"): text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    text = text.strip()
    return text[:-3].strip() if text.endswith("```") else text

def _str(value, name: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip(): raise ValueError(f"{name} 必须是非空字符串")
    if len(value.strip()) > limit: raise ValueError(f"{name} 超长（>{limit}）")
    return value

def _str_list(value, name: str, limit: int, nonempty: bool = False) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
        raise ValueError(f"{name} 必须是 str 列表")
    if nonempty and not value: raise ValueError(f"{name} 不能为空")
    if any(len(x.strip()) > limit for x in value): raise ValueError(f"{name} 元素超长（>{limit}）")
    return value

def _quiz(value) -> dict:
    if not isinstance(value, dict): raise ValueError("quiz 任务必须提供 dict 类型的 quiz")
    options = value.get("options")
    if not isinstance(options, list) or not options: raise ValueError("quiz.options 必须是非空 list")
    if len(options) > MAX_OPTIONS: raise ValueError(f"quiz.options 数量超限（>{MAX_OPTIONS}）")
    for opt in options:
        _str(opt, "quiz.option", LIM_OPT)
    answer = value.get("answer")
    if isinstance(answer, bool) or not isinstance(answer, int) or not 0 <= answer < len(options):
        raise ValueError("quiz.answer 必须是 0 <= answer < len(options) 的 int")
    out = {"q": _str(value.get("q"), "quiz.q", LIM_Q), "options": options, "answer": answer}
    if value.get("explanation") is not None: out["explanation"] = _str(value.get("explanation"), "quiz.explanation", LIM_EXPL)
    return out

def _task(value) -> dict:
    if not isinstance(value, dict): raise ValueError("每个 task 必须是 dict")
    kind = value.get("kind")
    if kind not in ("quiz", "artifact"): raise ValueError("task.kind 必须是 quiz 或 artifact")
    diff = value.get("difficulty")
    if isinstance(diff, bool) or not isinstance(diff, int) or not 0 <= diff <= 3:
        raise ValueError("difficulty 必须是 0-3 的整数")
    out = {"kind": kind, "title": _str(value.get("title"), "task.title", LIM_TITLE),
           "brief": _str(value.get("brief"), "task.brief", LIM_BRIEF), "difficulty": diff}
    if value.get("skills") is not None: out["skills"] = _str_list(value["skills"], "task.skills", LIM_ITEM)
    if value.get("acceptance") is not None:
        out["acceptance"] = _str_list(value["acceptance"], "task.acceptance", LIM_ITEM,
                                      nonempty=kind == "artifact")
    if kind == "artifact" and not out.get("acceptance"): raise ValueError("artifact 任务必须提供非空 acceptance")
    if kind == "quiz": out["quiz"] = _quiz(value.get("quiz"))
    return out

def _stage(value) -> dict:
    if not isinstance(value, dict): raise ValueError("每个 stage 必须是 dict")
    tasks = value.get("tasks")
    if not isinstance(tasks, list) or not tasks: raise ValueError("stage.tasks 必须是非空 list")
    if len(tasks) > MAX_TASKS: raise ValueError(f"stage.tasks 数量超限（>{MAX_TASKS}）")
    return {"title": _str(value.get("title"), "stage.title", LIM_TITLE), "tasks": [_task(t) for t in tasks]}

def validate_candidate_path(raw: dict) -> dict:
    """严格校验 LLM 输出：坏 JSON / 缺字段 / difficulty 越界 / 超长 / 非预期结构全拒。"""
    if not isinstance(raw, dict): raise ValueError("候选路径必须是 dict")
    stages = raw.get("stages")
    if not isinstance(stages, list) or not stages: raise ValueError("stages 必须是非空 list")
    if len(stages) > MAX_STAGES: raise ValueError(f"stages 数量超限（>{MAX_STAGES}）")
    return {"title": _str(raw.get("title"), "title", LIM_TITLE), "stages": [_stage(s) for s in stages]}

def _user_prompt(goal: str, interests: list[str]) -> str:
    return (
        f"学习目标：{goal}\n"
        f"兴趣点：{json.dumps(interests, ensure_ascii=False)}\n"
        "请输出以下结构的 JSON（字段不可省略）：\n"
        f"{json.dumps(_EXAMPLE, ensure_ascii=False, indent=2)}\n"
        "规则：stages 1-10 个、每 stage tasks 1-10 个；quiz 的 answer 为正确选项下标（0 起）；artifact 的 acceptance 至少 1 条；difficulty 取 0-3 整数；全部中文。")

def generate_candidate_path(goal: str, interests: list[str], client) -> dict:
    """调用 DeepSeek 生成候选路径（含 difficulty 0-3 标注），返回 raw dict（未校验）。"""
    if not isinstance(goal, str) or not goal.strip(): raise ValueError("goal 必须是非空字符串")
    if not isinstance(interests, list) or any(not isinstance(i, str) for i in interests):
        raise ValueError("interests 必须是 str 列表")
    resp = client.chat.completions.create(  # client 异常原样上抛，重试/报错归调用方
        model=DEFAULT_MODEL, temperature=0.3, max_tokens=MAX_TOKENS,
        messages=[{"role": "system", "content": _SYSTEM}, {"role": "user", "content": _user_prompt(goal, interests)}])
    content = resp.choices[0].message.content
    if not isinstance(content, str): raise ValueError("LLM 响应 content 必须是字符串")
    try:
        data = json.loads(_strip_fence(content))
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM 响应不是合法 JSON: {exc}") from exc
    if not isinstance(data, dict): raise ValueError("LLM 响应 JSON 必须是对象")
    return data
