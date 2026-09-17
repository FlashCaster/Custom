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
    return {
        "activities": [
            {"topic": "sets_inequalities", "minutes": 15, "material_basis": basis,
             "selected_statement_ids": [statement_id], "defer_if_old_knowledge_weak": False},
            {"topic": "function_concept", "minutes": 15, "material_basis": basis,
             "selected_statement_ids": [statement_id], "defer_if_old_knowledge_weak": True},
        ],
    }


def _client(payload: dict, usage=(21, 34), captured=None):
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False)))],
        usage=None if usage is None else SimpleNamespace(prompt_tokens=usage[0], completion_tokens=usage[1]),
    )
    def create(**kwargs):
        if captured is not None:
            captured.update(kwargs)
        return response
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


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
    assert plan["assumptions"] == generated_lesson_plans._progress_assumptions(student)
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
    assert plan["title"] == "高一数学备课稿"
    assert plan["activities"][1]["student_task"] == "根据已核准材料的函数概念表述，判断输入和输出关系并写出理由。"
    assert "每一个输入恰好对应一个输出" in plan["activities"][1]["answer_check"]


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


def test_generation_requires_both_topics_and_rejects_untrusted_extra_fields(db):
    student = _student()
    material = _selected_material(student["id"])
    raw = _candidate(material["id"], material["statements"][0]["id"])
    raw["activities"] = raw["activities"][:1]
    raw["school_progress"] = "学校已讲完函数性质"
    raw["title"] = "模型决定的备课稿标题"

    with pytest.raises(ValueError, match="候选字段"):
        generated_lesson_plans.generate(
            student["id"], {"course_objective": "集合与函数", "total_minutes": 120,
                            "math_minutes": 80, "old_knowledge_weak": False}, _client(raw),
        )

    assert store.list_generated_lesson_plans() == []


def test_generation_sends_a_minimal_student_context_without_identity_or_storage_metadata(db):
    student = _student()
    material = _selected_material(student["id"])
    captured = {}

    generated_lesson_plans.generate(
        student["id"], {"course_objective": "集合与函数", "total_minutes": 120,
                        "math_minutes": 80, "old_knowledge_weak": False},
        _client(_candidate(material["id"], material["statements"][0]["id"]), captured=captured),
    )

    student_context = generated_lesson_plans._student_context(student)
    assert student_context == {
        "grade": "高一", "subject": "数学",
        "observed_errors": ["集合条件代入后仍会漏看不等式方向"],
        "independent_tasks": ["能独立写一元一次不等式的变形理由"],
        "assumptions": [{"id": "school_progress", "kind": "school_progress", "source": "teacher_profile",
                         "status": "unknown", "known_content": []}],
    }
    prompt = captured["messages"][1]["content"]
    assert "小林" not in prompt
    assert "created_at" not in prompt


def test_generation_fails_without_reported_usage_instead_of_persisting_zero_tokens(db):
    student = _student()
    material = _selected_material(student["id"])

    with pytest.raises(ValueError, match="模型用量缺失"):
        generated_lesson_plans.generate(
            student["id"], {"course_objective": "集合与函数", "total_minutes": 120,
                            "math_minutes": 80, "old_knowledge_weak": False},
            _client(_candidate(material["id"], material["statements"][0]["id"]), usage=None),
        )

    assert store.list_generated_lesson_plans() == []


def test_manual_edit_save_persists_only_editable_fields_and_preserves_provenance(db):
    student = _student()
    material = _selected_material(student["id"])
    original = generated_lesson_plans.generate(
        student["id"], {"course_objective": "集合与函数", "total_minutes": 120,
                        "math_minutes": 80, "old_knowledge_weak": False},
        _client(_candidate(material["id"], material["statements"][0]["id"])),
    )
    edits = [dict(activity) for activity in original["activities"]]
    edits[0]["title"] = "集合检查（教师改写）"
    edits[0]["student_task"] = "先代入，再写每一步理由。"
    edits[0]["material_basis"] = []

    saved = generated_lesson_plans.save_manual_edits(original["id"], {
        "title": "更新后的备课稿", "activities": edits,
    })

    assert saved["title"] == "更新后的备课稿"
    assert saved["activities"][0]["student_task"] == "先代入，再写每一步理由。"
    assert saved["activities"][0]["material_basis"] == original["activities"][0]["material_basis"]


def test_generation_rejects_model_supplied_body_text_and_persists_only_template_text(db):
    student = _student()
    material = _selected_material(student["id"])
    raw = _candidate(material["id"], material["statements"][0]["id"])
    for field in ("title", "student_task", "answer_space", "feedback_record", "teacher_observation",
                  "teacher_prompt", "answer_check", "stuck_support"):
        raw["activities"][1][field] = "学生已经学过函数性质，请直接判断单调性。"

    with pytest.raises(ValueError, match="activity 包含不允许字段"):
        generated_lesson_plans.generate(
            student["id"], {"course_objective": "集合与函数", "total_minutes": 120,
                            "math_minutes": 80, "old_knowledge_weak": False}, _client(raw),
        )

    assert store.list_generated_lesson_plans() == []
