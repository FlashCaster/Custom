"""真实备课候选生成服务：可信上下文、模型候选校验与持久化。"""
from __future__ import annotations

import json

from backend import store


MODEL = "deepseek-chat"
MAX_TOKENS = 3000
_TEXT_FIELDS = (
    "title", "student_task", "answer_space", "feedback_record", "teacher_observation",
    "teacher_prompt", "answer_check", "stuck_support",
)
_TOPICS = {"sets_inequalities", "function_concept"}
_SYSTEM = (
    "你是高中一对一数学教师的备课助手。只输出 JSON，不要 Markdown 或解释。输出是待教师编辑和确认的候选，"
    "不是课堂事实。只能使用提供的已选择、实际已读材料内容及已选择的材料表述；不得引用未读页，"
    "不得把学校进度未知写成学生已经学习过任何内容。必须保留集合与不等式检查及函数概念活动。"
)


def _text(value, field: str, limit: int = 800) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} 必须是非空字符串")
    if len(value.strip()) > limit:
        raise ValueError(f"{field} 超长（>{limit}）")
    return value.strip()


def _positive_int(value, field: str, maximum: int = 600) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError(f"{field} 必须是 1-{maximum} 的整数")
    return value


def _strip_fence(content: str) -> str:
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1] if "\n" in content else content[3:]
    return content[:-3].strip() if content.strip().endswith("```") else content.strip()


def _request(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("生成请求必须是对象")
    total = _positive_int(data.get("total_minutes"), "total_minutes")
    math = _positive_int(data.get("math_minutes"), "math_minutes")
    if math > total:
        raise ValueError("math_minutes 不得大于 total_minutes")
    weak = data.get("old_knowledge_weak", False)
    if not isinstance(weak, bool):
        raise ValueError("old_knowledge_weak 必须是布尔值")
    return {"course_objective": _text(data.get("course_objective"), "course_objective", 500),
            "total_minutes": total, "math_minutes": math, "old_knowledge_weak": weak}


def _material_context(student_id: int) -> list[dict]:
    selections = store.list_material_selection_records(student_id)
    if not selections:
        raise ValueError("请先为该学生选择至少一份参考材料")
    selected_statement_ids = {choice["statement_id"] for choice in store.list_reference_statement_choices()
                              if choice["student_id"] == student_id}
    context = []
    for selection in selections:
        material = selection["material"]
        selected_pages = set(selection["selected_pages"])
        read_pages = [{"page": page["page"], "content": page["content"]}
                      for page in material["read_pages"] if page["page"] in selected_pages]
        if not read_pages:
            continue
        statements = [
            {"id": item["id"], "topic": item["topic"], "text": item["text"], "page": item["page"]}
            for item in material["statements"]
            if item["id"] in selected_statement_ids and item["page"] in selected_pages
        ]
        context.append({"material_id": material["id"], "title": material["title"],
                        "selected_pages": selection["selected_pages"], "usage_scope": selection["usage_scope"],
                        "read_pages": read_pages, "selected_statements": statements})
    if not context:
        raise ValueError("所选材料没有实际读取的页面，不能生成备课稿")
    return context


def _source_index(context: list[dict]) -> tuple[dict[tuple[int, int], str], set[int]]:
    pages = {}
    statement_ids = set()
    for material in context:
        for page in material["read_pages"]:
            pages[(material["material_id"], page["page"])] = page["content"]
        statement_ids.update(item["id"] for item in material["selected_statements"])
    return pages, statement_ids


def _validate_activity(raw, position: int, pages: dict[tuple[int, int], str],
                       selected_statement_ids: set[int], math_minutes: int) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("每个 activity 必须是对象")
    topic = raw.get("topic")
    if topic not in _TOPICS:
        raise ValueError("activity.topic 必须是 sets_inequalities 或 function_concept")
    out = {field: _text(raw.get(field), f"activity.{field}") for field in _TEXT_FIELDS}
    out["topic"] = topic
    out["minutes"] = _positive_int(raw.get("minutes"), "activity.minutes", math_minutes)
    defer = raw.get("defer_if_old_knowledge_weak")
    if not isinstance(defer, bool):
        raise ValueError("activity.defer_if_old_knowledge_weak 必须是布尔值")
    out["defer_if_old_knowledge_weak"] = defer
    bases = raw.get("material_basis")
    if not isinstance(bases, list) or not bases:
        raise ValueError("activity.material_basis 必须是非空列表")
    out_bases = []
    for basis in bases:
        if not isinstance(basis, dict):
            raise ValueError("activity.material_basis 项必须是对象")
        material_id, page = basis.get("material_id"), basis.get("page")
        if (isinstance(material_id, bool) or not isinstance(material_id, int) or isinstance(page, bool)
                or not isinstance(page, int) or (material_id, page) not in pages):
            raise ValueError("活动来源必须来自已选择且实际读取的材料页")
        locator = _text(basis.get("locator"), "activity.material_basis.locator", 300)
        if locator not in pages[(material_id, page)]:
            raise ValueError("活动来源定位文字必须在已读取材料正文中")
        out_bases.append({"material_id": material_id, "page": page, "locator": locator})
    out["material_basis"] = out_bases
    statement_ids = raw.get("selected_statement_ids")
    if not isinstance(statement_ids, list) or any(isinstance(item, bool) or not isinstance(item, int)
                                                   for item in statement_ids):
        raise ValueError("activity.selected_statement_ids 必须是整数列表")
    if not set(statement_ids).issubset(selected_statement_ids):
        raise ValueError("活动只能采用教师已选择的材料表述")
    out["selected_statement_ids"] = statement_ids
    out["position"] = position
    return out


def validate_candidate(raw: dict, student: dict, context: list[dict], request: dict) -> dict:
    """验证不可信模型候选，并丢弃未声明字段。"""
    if not isinstance(raw, dict):
        raise ValueError("备课候选必须是对象")
    if raw.get("school_progress_status") != student["school_progress_status"]:
        raise ValueError("候选不得改变 school_progress_status")
    if raw.get("school_progress") != student["school_progress"]:
        raise ValueError("候选不得把 school_progress 写成未经核实的事实")
    activities = raw.get("activities")
    if not isinstance(activities, list) or not activities:
        raise ValueError("activities 必须是非空列表")
    pages, selected_statement_ids = _source_index(context)
    output = [_validate_activity(item, position, pages, selected_statement_ids, request["math_minutes"])
              for position, item in enumerate(activities)]
    topics = {activity["topic"] for activity in output}
    if topics != _TOPICS:
        raise ValueError("候选必须同时保留集合与不等式检查和函数概念活动")
    if request["old_knowledge_weak"] and not any(
            activity["topic"] == "function_concept" and activity["defer_if_old_knowledge_weak"]
            for activity in output):
        raise ValueError("旧知识薄弱时函数活动必须允许推迟，但不得删除")
    if sum(activity["minutes"] for activity in output) > request["math_minutes"]:
        raise ValueError("活动数学时长之和不得超过 math_minutes")
    return {"title": _text(raw.get("title"), "title", 120), "activities": output}


def _usage(response) -> dict:
    usage = getattr(response, "usage", None)
    prompt = getattr(usage, "prompt_tokens", 0) or 0
    completion = getattr(usage, "completion_tokens", 0) or 0
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in (prompt, completion)):
        raise ValueError("模型用量格式无效")
    return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion}


def _generate_raw(student: dict, request: dict, context: list[dict], client) -> tuple[dict, dict]:
    user = (
        f"学生档案：{json.dumps(student, ensure_ascii=False)}\n"
        f"本次课程：{json.dumps(request, ensure_ascii=False)}\n"
        f"允许使用的材料：{json.dumps(context, ensure_ascii=False)}\n"
        "输出 JSON: {title, school_progress_status, school_progress, activities}。每个 activity 必含 "
        "topic(sets_inequalities/function_concept)、title、student_task、answer_space、feedback_record、"
        "teacher_observation、teacher_prompt、answer_check、stuck_support、minutes、"
        "defer_if_old_knowledge_weak、material_basis([{material_id,page,locator}])、selected_statement_ids。"
        "若 old_knowledge_weak 为 true，保留函数活动并标记可推迟。"
    )
    response = client.chat.completions.create(
        model=MODEL, temperature=0.2, max_tokens=MAX_TOKENS,
        messages=[{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
    )
    content = response.choices[0].message.content
    if not isinstance(content, str):
        raise ValueError("LLM 响应 content 必须是字符串")
    try:
        raw = json.loads(_strip_fence(content))
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM 响应不是合法 JSON: {exc}") from exc
    return raw, _usage(response)


def generate(student_id: int, data: dict, client) -> dict:
    """主动生成时唯一调用模型；先校验候选，后写候选稿和本次用量。"""
    if isinstance(student_id, bool) or not isinstance(student_id, int):
        raise ValueError("student_id 必须是整数")
    student = store.get_student_record(student_id)
    if student is None:
        raise ValueError(f"student {student_id} 不存在")
    request = _request(data)
    context = _material_context(student_id)
    raw, usage = _generate_raw(student, request, context, client)
    candidate = validate_candidate(raw, student, context, request)
    plan_id = store.create_generated_lesson_plan_with_usage({
        "student_id": student_id, "title": candidate["title"], "course_objective": request["course_objective"],
        "total_minutes": request["total_minutes"], "math_minutes": request["math_minutes"],
        "old_knowledge_weak": request["old_knowledge_weak"], "material_context": context,
        "activities": candidate["activities"],
    }, usage, MODEL)
    return {**store.get_generated_lesson_plan(plan_id), "usage": usage, "label": "待教师编辑的候选"}


def teacher_manuscript(lesson_plan_id: int) -> dict | None:
    plan = store.get_generated_lesson_plan(lesson_plan_id)
    if plan is None:
        return None
    usages = store.list_generation_usage_records(lesson_plan_id)
    usage = usages[-1] if usages else {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    return {**plan, "usage": {key: usage[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens")},
            "label": "待教师编辑的候选"}
