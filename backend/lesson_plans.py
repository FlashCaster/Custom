"""备课稿领域服务：示例初始化、活动契约和教师/学生稿投影。"""
from __future__ import annotations

from backend import store


_EXAMPLE_ACTIVITY_FIELDS = (
    "id", "position", "title", "student_task", "answer_space", "feedback_record",
    "teacher_observation", "teacher_prompt", "answer_check", "stuck_support",
)

_DEFAULT_EXAMPLE = {
    "id": "default",
    "title": "集合与函数备课稿",
    "activities": [
        {"id": "set-inequality-check", "position": 0, "title": "集合与不等式检查",
         "student_task": "判断给出的元素是否属于集合，并写出每一步判断理由。",
         "answer_space": "判断：____________________\n理由：____________________",
         "feedback_record": "我在哪一步不确定：____________________",
         "teacher_observation": "先看学生是否主动区分元素、集合与不等式条件。",
         "teacher_prompt": "你用了哪个条件？把它代回去会发生什么？",
         "answer_check": "核查集合符号、条件范围和不等式方向是否一致。",
         "stuck_support": "让学生先圈出条件中的变量和范围，再口头说出判断依据。"},
        {"id": "function-relation-judgement", "position": 1, "title": "函数关系判断",
         "student_task": "判断每个关系是不是函数，并写出理由。",
         "answer_space": "判断：____________________\n理由：____________________",
         "feedback_record": "我检查了输入和输出：____________________",
         "teacher_observation": "观察学生是否说出“每个输入恰好一个输出”，而非只凭图形印象。",
         "teacher_prompt": "同一个输入可以对应几个输出？逐个输入检查。",
         "answer_check": "函数要求定义域内每个输入恰好对应一个输出。",
         "stuck_support": "把关系写成输入与输出的配对，先检查有没有一个输入连到两个输出。"},
        {"id": "function-domain-practice", "position": 2, "title": "函数定义域练习",
         "student_task": "如果前一项完成顺利，从情境中写出函数自变量的取值范围。",
         "answer_space": "自变量表示：____________________\n取值范围：____________________",
         "feedback_record": "情境限制是：____________________",
         "teacher_observation": "仅在函数判断已稳固时进入，检查学生是否从情境限制而非公式习惯确定范围。",
         "teacher_prompt": "这个量在情境里能取负数吗？还需要满足什么条件？",
         "answer_check": "定义域由情境和表达式共同限制，不能只看一种限制。",
         "stuck_support": "先用一句话说明自变量代表什么，再列出不能出现的取值。"},
    ],
}

_STUDENT_FIELDS = ("id", "position", "title", "student_task", "answer_space", "feedback_record")


def _nonempty_text(value, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} 必须是非空字符串")
    return value


def validate_activities(activities) -> list[dict]:
    if not isinstance(activities, list) or not activities:
        raise ValueError("activities 必须是非空列表")
    validated = []
    for position, activity in enumerate(activities):
        if not isinstance(activity, dict):
            raise ValueError("每个 activity 必须是对象")
        output = {}
        for field in _EXAMPLE_ACTIVITY_FIELDS:
            value = activity.get(field)
            if field == "position":
                if isinstance(value, bool) or not isinstance(value, int) or value != position:
                    raise ValueError("activity.position 必须从 0 开始连续编号")
            else:
                _nonempty_text(value, f"activity.{field}")
            output[field] = value
        validated.append(output)
    return validated


def _teacher_projection(record: dict) -> dict:
    return {"id": record["id"], "label": "示例", "title": record["title"],
            "activities": record["activities"], "updated_at": record["updated_at"]}


def _get_record(example_id: str) -> dict | None:
    if example_id == _DEFAULT_EXAMPLE["id"]:
        store.create_lesson_plan_example_if_missing(
            _DEFAULT_EXAMPLE["id"], _DEFAULT_EXAMPLE["title"], _DEFAULT_EXAMPLE["activities"])
    return store.get_lesson_plan_example(example_id)


def teacher_manuscript(example_id: str) -> dict | None:
    record = _get_record(example_id)
    return _teacher_projection(record) if record is not None else None


def get_example(example_id: str) -> dict | None:
    """兼容服务层调用；示例读取始终返回教师稿投影。"""
    return teacher_manuscript(example_id)


def update_example(example_id: str, title: str, activities: list) -> dict | None:
    _nonempty_text(example_id, "example_id")
    if _get_record(example_id) is None:
        return None
    _nonempty_text(title, "title")
    record = store.update_lesson_plan_example_record(example_id, title, validate_activities(activities))
    return _teacher_projection(record) if record is not None else None


def student_task_page(example_id: str) -> dict | None:
    record = _get_record(example_id)
    if record is None:
        return None
    example = _teacher_projection(record)
    return {"id": example["id"], "label": example["label"], "title": example["title"],
            "activities": [{field: activity[field] for field in _STUDENT_FIELDS}
                           for activity in example["activities"]], "updated_at": example["updated_at"]}
