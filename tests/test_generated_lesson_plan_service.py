"""票 #3：从已核准材料生成可编辑备课候选的服务层验收。"""
from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend import generated_lesson_plans, prep, store


_BASE = Path(__file__).resolve().parent.parent / "data" / ".test_dbs"


@pytest.fixture
def db(monkeypatch):
    directory = _BASE / uuid.uuid4().hex
    os.makedirs(directory, exist_ok=True)
    path = directory / "test.db"
    monkeypatch.setattr(store, "DB_PATH", path)
    store.init_db(path)
    yield path
    shutil.rmtree(directory, ignore_errors=True)


def _student():
    return prep.student_profile({
        "name": "小林", "grade": "高一", "subject": "数学",
        "observed_errors": ["集合条件代入后仍会漏看不等式方向"],
        "independent_tasks": ["能独立写一元一次不等式的变形理由"],
        "school_progress_status": "unknown", "school_progress": None,
    })


def _selected_material(student_id: int):
    material = prep.reference_material({
        "title": "函数概念讲义", "file_identifier": "function.pdf",
        "selected_pages": [12, 13], "usage_scope": "只核查函数概念和定义域活动",
        "read_pages": [{"page": 12, "content": "函数要求定义域内每一个输入恰好对应一个输出。"}],
        "unread_pages": [13],
        "statements": [{"topic": "函数定义", "page": 12,
                        "text": "函数要求定义域内每一个输入恰好对应一个输出。"}],
    })
    prep.select_material(student_id, material["id"], {
        "selected_pages": [12, 13], "usage_scope": "本次函数概念核查；第 13 页不可引用",
    })
    prep.choose_statement(student_id, material["statements"][0]["id"])
    return material


def _candidate(material_id: int, statement_id: int):
    basis = [{"material_id": material_id, "page": 12, "locator": "每一个输入恰好对应一个输出"}]
    common = {
        "answer_space": "判断：________________", "feedback_record": "我不确定：________________",
        "teacher_observation": "观察学生是否写出理由", "teacher_prompt": "逐个检查输入和输出。",
        "answer_check": "核查依据：定义域内每一个输入恰好对应一个输出。",
        "stuck_support": "先列出输入，再逐项配对。", "minutes": 15,
        "material_basis": basis, "selected_statement_ids": [statement_id],
    }
    return {
        "title": "小林的集合与函数备课稿", "school_progress_status": "unknown",
        "school_progress": None,
        "activities": [
            {**common, "topic": "sets_inequalities", "title": "集合与不等式检查",
             "student_task": "代入集合条件并写出不等式判断理由。",
             "defer_if_old_knowledge_weak": False},
            {**common, "topic": "function_concept", "title": "函数概念判断",
             "student_task": "判断每个输入是否恰好对应一个输出，并写理由。",
             "defer_if_old_knowledge_weak": True},
        ],
    }


def _client(payload: dict, usage=(21, 34)):
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False)))],
        usage=SimpleNamespace(prompt_tokens=usage[0], completion_tokens=usage[1]),
    )
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: response)))


def test_generation_uses_only_selected_read_material_and_persists_candidate_and_usage(db):
    student = _student()
    material = _selected_material(student["id"])
    raw = _candidate(material["id"], material["statements"][0]["id"])

    plan = generated_lesson_plans.generate(
        student["id"], {"course_objective": "先检查集合与不等式，再视情况进入函数概念",
                        "total_minutes": 120, "math_minutes": 80, "old_knowledge_weak": True},
        _client(raw),
    )

    assert plan["student_id"] == student["id"]
    assert [activity["topic"] for activity in plan["activities"]] == ["sets_inequalities", "function_concept"]
    assert plan["activities"][1]["defer_if_old_knowledge_weak"] is True
    assert plan["material_context"] == [{
        "material_id": material["id"], "title": "函数概念讲义", "selected_pages": [12, 13],
        "usage_scope": "本次函数概念核查；第 13 页不可引用",
        "read_pages": [{"page": 12, "content": "函数要求定义域内每一个输入恰好对应一个输出。"}],
        "selected_statements": [{"id": material["statements"][0]["id"], "topic": "函数定义",
                                 "text": "函数要求定义域内每一个输入恰好对应一个输出。", "page": 12}],
    }]
    assert plan["usage"] == {"prompt_tokens": 21, "completion_tokens": 34, "total_tokens": 55}
    assert store.get_generated_lesson_plan(plan["id"])["activities"] == plan["activities"]
    assert store.list_generation_usage_records(plan["id"])[0]["total_tokens"] == 55


def test_generation_rejects_unread_or_unselected_sources_and_does_not_create_a_plan(db):
    student = _student()
    material = _selected_material(student["id"])
    raw = _candidate(material["id"], material["statements"][0]["id"])
    raw["activities"][0]["material_basis"] = [{"material_id": material["id"], "page": 13, "locator": "不存在"}]

    with pytest.raises(ValueError, match="已选择且实际读取"):
        generated_lesson_plans.generate(
            student["id"], {"course_objective": "集合与函数", "total_minutes": 120,
                            "math_minutes": 80, "old_knowledge_weak": False}, _client(raw),
        )

    assert store.list_generated_lesson_plans() == []


def test_generation_rejects_a_material_statement_that_the_teacher_did_not_choose(db):
    student = _student()
    material = _selected_material(student["id"])
    raw = _candidate(material["id"], material["statements"][0]["id"])
    raw["activities"][0]["selected_statement_ids"] = [999]

    with pytest.raises(ValueError, match="教师已选择"):
        generated_lesson_plans.generate(
            student["id"], {"course_objective": "集合与函数", "total_minutes": 120,
                            "math_minutes": 80, "old_knowledge_weak": False}, _client(raw),
        )

    assert store.list_generated_lesson_plans() == []


def test_generation_requires_both_topics_and_never_turns_unknown_progress_into_a_fact(db):
    student = _student()
    material = _selected_material(student["id"])
    raw = _candidate(material["id"], material["statements"][0]["id"])
    raw["activities"] = raw["activities"][:1]
    raw["school_progress"] = "学校已讲完函数性质"

    with pytest.raises(ValueError, match="school_progress"):
        generated_lesson_plans.generate(
            student["id"], {"course_objective": "集合与函数", "total_minutes": 120,
                            "math_minutes": 80, "old_knowledge_weak": False}, _client(raw),
        )

    assert store.list_generated_lesson_plans() == []
