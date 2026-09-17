"""真实备课候选生成服务：可信上下文、模型候选校验与持久化。"""
from __future__ import annotations

import json

from backend import store


MODEL = "deepseek-chat"
MAX_TOKENS = 3000
VERIFIER_MAX_TOKENS = 800
_TEXT_FIELDS = (
    "title", "student_task", "answer_space", "feedback_record", "teacher_observation",
    "teacher_prompt", "answer_check", "stuck_support",
)
_EDITABLE_ACTIVITY_FIELDS = ("title", *_TEXT_FIELDS[1:])
_TOPICS = {"sets_inequalities", "function_concept"}
_PROGRESS_ASSUMPTION = "school_progress"
_INDEPENDENT_PROGRESS_FIELDS = {"school_progress", "school_progress_status", "progress_statement"}
_SYSTEM = (
    "你是高中一对一数学教师的备课助手。只输出 JSON，不要 Markdown 或解释。输出是待教师编辑和确认的候选，"
    "不是课堂事实。只能使用提供的已选择、实际已读材料内容及已选择的材料表述；不得引用未读页，"
    "不得把学校进度未知写成学生已经学习过任何内容。必须保留集合与不等式检查及函数概念活动。"
)
_VERIFIER_SYSTEM = (
    "你是备课候选的语义安全核验器。只输出严格 JSON，不要 Markdown 或解释。核验所有候选正文是否把学校进度"
    "未知当作事实，或是否声称学生学习过教师档案未明确记录的内容。学校进度和学习内容只能以给定的"
    "teacher_profile 结构化 assumptions 为事实依据；材料内容不是学校教学进度事实。"
    "输出必须严格为 {verdict,activity_position,field,reason}：通过时 verdict=pass 且后三项都为 null；"
    "不通过时 verdict=fail，activity_position 是有问题活动的 0 起位置，field 是对应正文栏位，reason 是简短原因。"
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


def _progress_assumptions(student: dict) -> list[dict]:
    """学校进度是唯一允许的结构化进度依据，不接受模型自由文字声明。"""
    status = student["school_progress_status"]
    known_content = [] if status == "unknown" else [student["school_progress"]]
    return [{"id": _PROGRESS_ASSUMPTION, "kind": "school_progress", "source": "teacher_profile",
             "status": status, "known_content": known_content}]


def _student_context(student: dict) -> dict:
    """模型只需教学决策相关事实；身份与持久化元数据永不进入提示词。"""
    return {
        "grade": student["grade"], "subject": student["subject"],
        "observed_errors": student["observed_errors"], "independent_tasks": student["independent_tasks"],
        "assumptions": _progress_assumptions(student),
    }


def _reject_independent_progress_fields(value) -> None:
    """检查结构键而非自由文本；学校进度只能出现在 assumptions 的受限结构内。"""
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in _INDEPENDENT_PROGRESS_FIELDS:
                raise ValueError("候选不得返回独立的学校进度声明")
            _reject_independent_progress_fields(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_independent_progress_fields(nested)


def _validate_assumptions(value, student: dict) -> list[dict]:
    expected = _progress_assumptions(student)
    if value != expected:
        raise ValueError("候选 assumptions 必须与教师档案中的学校进度依据完全一致")
    return expected


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
    if raw.get("assumption_ids") != [_PROGRESS_ASSUMPTION]:
        raise ValueError("activity.assumption_ids 必须引用学校进度的结构化依据")
    out["assumption_ids"] = [_PROGRESS_ASSUMPTION]
    out["position"] = position
    return out


def validate_candidate(raw: dict, student: dict, context: list[dict], request: dict) -> dict:
    """验证不可信模型候选，并丢弃未声明字段。"""
    if not isinstance(raw, dict):
        raise ValueError("备课候选必须是对象")
    _reject_independent_progress_fields(raw)
    assumptions = _validate_assumptions(raw.get("assumptions"), student)
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
    return {"title": _text(raw.get("title"), "title", 120), "activities": output,
            "assumptions": assumptions}


def _usage(response) -> dict:
    usage = getattr(response, "usage", None)
    if usage is None:
        raise ValueError("模型用量缺失，未保存备课候选")
    prompt = getattr(usage, "prompt_tokens", None)
    completion = getattr(usage, "completion_tokens", None)
    if prompt is None or completion is None:
        raise ValueError("模型用量缺失，未保存备课候选")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in (prompt, completion)):
        raise ValueError("模型用量格式无效")
    return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion}


def _call_json(client, system: str, user: str, max_tokens: int) -> tuple[dict, dict]:
    response = client.chat.completions.create(
        model=MODEL, temperature=0.0, max_tokens=max_tokens,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    content = response.choices[0].message.content
    if not isinstance(content, str):
        raise ValueError("LLM 响应 content 必须是字符串")
    try:
        raw = json.loads(_strip_fence(content))
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM 响应不是合法 JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("LLM 响应 JSON 必须是对象")
    return raw, _usage(response)


def _generate_raw(student: dict, request: dict, context: list[dict], client) -> tuple[dict, dict]:
    user = (
        f"学生档案：{json.dumps(_student_context(student), ensure_ascii=False)}\n"
        f"本次课程：{json.dumps(request, ensure_ascii=False)}\n"
        f"允许使用的材料：{json.dumps(context, ensure_ascii=False)}\n"
        "输出 JSON: {title, assumptions, activities}。不得输出 school_progress、school_progress_status 或任何独立进度声明。"
        "assumptions 必须原样保留学生档案的结构化学校进度依据；每个 activity 必须引用 assumption_ids:[school_progress]。"
        "每个 activity 必含 "
        "topic(sets_inequalities/function_concept)、title、student_task、answer_space、feedback_record、"
        "teacher_observation、teacher_prompt、answer_check、stuck_support、minutes、"
        "defer_if_old_knowledge_weak、material_basis([{material_id,page,locator}])、selected_statement_ids、assumption_ids。"
        "若 old_knowledge_weak 为 true，保留函数活动并标记可推迟。"
    )
    return _call_json(client, _SYSTEM, user, MAX_TOKENS)


def _validate_verdict(raw: dict, activity_count: int) -> dict:
    required = {"verdict", "activity_position", "field", "reason"}
    if set(raw) != required or raw.get("verdict") not in ("pass", "fail"):
        raise ValueError("verifier verdict 必须是严格的 pass/fail 结构")
    if raw["verdict"] == "pass":
        if any(raw[field] is not None for field in ("activity_position", "field", "reason")):
            raise ValueError("verifier verdict=pass 时不得包含违规定位")
        return raw
    position, field, reason = raw["activity_position"], raw["field"], raw["reason"]
    if (isinstance(position, bool) or not isinstance(position, int) or not 0 <= position < activity_count
            or field not in _TEXT_FIELDS or not isinstance(reason, str) or not reason.strip()):
        raise ValueError("verifier verdict=fail 必须提供合法活动、字段和原因")
    return raw


def _verify_candidate(candidate: dict, student: dict, verifier) -> tuple[dict, dict]:
    if verifier is None:
        raise ValueError("语义 verifier 未配置，未保存备课候选")
    teacher_profile = {
        "assumptions": _progress_assumptions(student),
        "observed_errors": student["observed_errors"],
        "independent_tasks": student["independent_tasks"],
    }
    user = (
        f"teacher_profile：{json.dumps(teacher_profile, ensure_ascii=False)}\n"
        f"candidate：{json.dumps(candidate, ensure_ascii=False)}\n"
        "核验候选全部正文，按规定返回 verdict。"
    )
    raw, usage = _call_json(verifier, _VERIFIER_SYSTEM, user, VERIFIER_MAX_TOKENS)
    return _validate_verdict(raw, len(candidate["activities"])), usage


def _combined_usage(generation: dict, verification: dict) -> dict:
    return {key: generation[key] + verification[key]
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")}


def generate(student_id: int, data: dict, client, verifier=None) -> dict:
    """一次主动生成串行完成候选和 fail-closed 语义核验，成功后才写候选稿与合计用量。"""
    if isinstance(student_id, bool) or not isinstance(student_id, int):
        raise ValueError("student_id 必须是整数")
    student = store.get_student_record(student_id)
    if student is None:
        raise ValueError(f"student {student_id} 不存在")
    request = _request(data)
    context = _material_context(student_id)
    raw, usage = _generate_raw(student, request, context, client)
    candidate = validate_candidate(raw, student, context, request)
    verdict, verifier_usage = _verify_candidate(candidate, student, verifier)
    if verdict["verdict"] == "fail":
        raise ValueError(f"语义 verifier 拒绝活动 {verdict['activity_position']} 的 {verdict['field']}：{verdict['reason']}")
    usage = _combined_usage(usage, verifier_usage)
    plan_id = store.create_generated_lesson_plan_with_usage({
        "student_id": student_id, "title": candidate["title"], "course_objective": request["course_objective"],
        "total_minutes": request["total_minutes"], "math_minutes": request["math_minutes"],
        "old_knowledge_weak": request["old_knowledge_weak"], "material_context": context,
        "activities": candidate["activities"],
    }, usage, MODEL)
    return {**store.get_generated_lesson_plan(plan_id), "usage": usage, "assumptions": candidate["assumptions"],
            "label": "待教师编辑的候选"}


def teacher_manuscript(lesson_plan_id: int) -> dict | None:
    plan = store.get_generated_lesson_plan(lesson_plan_id)
    if plan is None:
        return None
    usages = store.list_generation_usage_records(lesson_plan_id)
    usage = usages[-1] if usages else None
    student = store.get_student_record(plan["student_id"])
    if student is None:
        raise ValueError(f"student {plan['student_id']} 不存在")
    response_usage = ({key: usage[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens")}
                      if usage is not None else None)
    return {**plan, "usage": response_usage, "assumptions": _progress_assumptions(student),
            "label": "待教师编辑的候选"}


def _manual_activities(current: list[dict], submitted) -> list[dict]:
    if not isinstance(submitted, list) or len(submitted) != len(current):
        raise ValueError("activities 必须保留现有活动数量和顺序")
    updated = []
    for position, (original, edit) in enumerate(zip(current, submitted)):
        if not isinstance(edit, dict) or edit.get("position") != position:
            raise ValueError("活动编辑必须保留 position")
        activity = dict(original)
        for field in _EDITABLE_ACTIVITY_FIELDS:
            activity[field] = _text(edit.get(field), f"activity.{field}")
        updated.append(activity)
    return updated


def save_manual_edits(lesson_plan_id: int, data: dict) -> dict | None:
    """仅保存教师普通文字编辑；不引入局部 AI 修改、差异预览或版本恢复。"""
    if not isinstance(data, dict):
        raise ValueError("备课稿保存请求必须是对象")
    current = store.get_generated_lesson_plan(lesson_plan_id)
    if current is None:
        return None
    title = _text(data.get("title"), "title", 120)
    activities = _manual_activities(current["activities"], data.get("activities"))
    store.update_generated_lesson_plan_record(lesson_plan_id, title, activities)
    return teacher_manuscript(lesson_plan_id)
