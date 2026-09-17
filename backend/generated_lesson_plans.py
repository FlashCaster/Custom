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
_EDITABLE_ACTIVITY_FIELDS = ("title", *_TEXT_FIELDS[1:])
_TOPICS = {"sets_inequalities", "function_concept"}
_PROGRESS_ASSUMPTION = "school_progress"
_CANDIDATE_FIELDS = {"activities"}
_ACTIVITY_FIELDS = {"topic", "minutes", "defer_if_old_knowledge_weak", "material_basis", "selected_statement_ids"}
_BASIS_FIELDS = {"material_id", "page", "locator"}
_SYSTEM = (
    "你是高中一对一数学备课的活动规划器。只输出 JSON，不要 Markdown 或解释。你只能输出 "
    "{activities:[...]}；每个 activity 只允许 topic、minutes、defer_if_old_knowledge_weak、"
    "material_basis、selected_statement_ids 五个字段。不得输出标题、任务、答案、观察、追问、学生状态、"
    "学校进度或任何其他文本。material_basis 必须选用提供的已核准材料来源。必须保留集合与不等式检查及函数概念活动。"
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
    if set(raw) != _ACTIVITY_FIELDS:
        raise ValueError("activity 包含不允许字段")
    topic = raw.get("topic")
    if topic not in _TOPICS:
        raise ValueError("activity.topic 必须是 sets_inequalities 或 function_concept")
    out = {"topic": topic}
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
        if set(basis) != _BASIS_FIELDS:
            raise ValueError("activity.material_basis 包含不允许字段")
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


def _source_text(activity: dict) -> str:
    return "；".join(f"“{basis['locator']}”" for basis in activity["material_basis"])


def _template_activity(activity: dict) -> dict:
    """把不可信规划投影为固定教学文本；只有已验证的来源定位可嵌入正文。"""
    source = _source_text(activity)
    if activity["topic"] == "sets_inequalities":
        fields = {
            "title": "集合与不等式检查",
            "student_task": "根据已核准材料中的条件，完成集合与不等式判断并写出每一步依据。",
            "answer_space": "判断：____________________\n理由：____________________",
            "feedback_record": "我在哪一步不确定：____________________",
            "teacher_observation": "观察条件代入、不等式方向核对和理由书写。",
            "teacher_prompt": "你代入了哪个条件？不等式方向需要怎样核对？",
            "answer_check": f"核查标准：对照已核准材料定位{source}，逐项检查条件与判断理由。",
            "stuck_support": "先圈出变量与条件，再逐步代入并记录每一步。",
        }
    else:
        fields = {
            "title": "函数概念判断",
            "student_task": "根据已核准材料的函数概念表述，判断输入和输出关系并写出理由。",
            "answer_space": "判断：____________________\n理由：____________________",
            "feedback_record": "我检查的输入和输出：____________________",
            "teacher_observation": "观察输入是否逐项核对，以及理由是否写完整。",
            "teacher_prompt": "请逐个检查输入；每个输入对应了几个输出？",
            "answer_check": f"核查标准：对照已核准材料定位{source}，检查每个输入与输出的对应关系。",
            "stuck_support": "先把关系写成输入和输出的配对，再逐项核对。",
        }
    return {**activity, **fields}


def validate_candidate(raw: dict, student: dict, context: list[dict], request: dict) -> dict:
    """验证受限活动规划，并投影为应用拥有的确定性教学文本。"""
    if not isinstance(raw, dict):
        raise ValueError("备课候选必须是对象")
    if set(raw) != _CANDIDATE_FIELDS:
        raise ValueError("候选字段不受允许")
    activities = raw.get("activities")
    if not isinstance(activities, list) or not activities:
        raise ValueError("activities 必须是非空列表")
    pages, selected_statement_ids = _source_index(context)
    output = [_template_activity(_validate_activity(item, position, pages, selected_statement_ids,
                                                     request["math_minutes"]))
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
    return {"title": f"{student['grade']}{student['subject']}备课稿", "activities": output,
            "assumptions": _progress_assumptions(student)}


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
        "输出 JSON 仅含 activities。每个 activity 仅含 topic(sets_inequalities/function_concept)、minutes、"
        "defer_if_old_knowledge_weak、material_basis([{material_id,page,locator}])、selected_statement_ids。"
        "不要输出任何标题、学生任务、答案、观察、追问、学校进度、学生状态或其他文字。"
        "若 old_knowledge_weak 为 true，保留函数活动并标记可推迟。"
    )
    return _call_json(client, _SYSTEM, user, MAX_TOKENS)


def generate(student_id: int, data: dict, client) -> dict:
    """一次主动生成只接受受限活动规划；完整教师稿由应用模板确定性生成。"""
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
