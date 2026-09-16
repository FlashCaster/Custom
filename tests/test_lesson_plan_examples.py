"""备课示例入口：教师稿、学生任务页和独立示例存储的 API 验收。"""
from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import store
from backend.main import app


_BASE = Path(__file__).resolve().parent.parent / "data" / ".test_dbs"


@pytest.fixture
def api(monkeypatch):
    """每个用例使用独立数据库，示例数据由公开入口按需创建。"""
    directory = _BASE / uuid.uuid4().hex
    os.makedirs(directory, exist_ok=True)
    monkeypatch.setattr(store, "DB_PATH", directory / "test.db")
    with TestClient(app) as client:
        yield client
    shutil.rmtree(directory, ignore_errors=True)


def test_example_lesson_plan_is_browsable_without_a_real_student(api):
    """首次打开可读取明确标为示例的集合与函数备课稿，不创建通用学习路径记录。"""
    response = api.get("/lesson-plan-examples/default")

    assert response.status_code == 200
    plan = response.json()
    assert plan["label"] == "示例"
    assert "集合" in plan["title"] and "函数" in plan["title"]
    assert [activity["title"] for activity in plan["activities"]] == [
        "集合与不等式检查",
        "函数关系判断",
        "函数定义域练习",
    ]
    assert api.get("/goals").json() == []


def test_teacher_and_student_pages_project_the_same_example_activities(api):
    """两种页面共享活动文本，学生页只得到学生可见字段。"""
    example = api.get("/lesson-plan-examples/default").json()
    teacher = api.get("/lesson-plan-examples/default/teacher-manuscript")
    student = api.get("/lesson-plan-examples/default/student-task-page")

    assert teacher.status_code == 200
    assert student.status_code == 200
    teacher_activity = teacher.json()["activities"][1]
    student_activity = student.json()["activities"][1]
    source_activity = example["activities"][1]
    assert student_activity == {
        "id": source_activity["id"],
        "position": source_activity["position"],
        "title": source_activity["title"],
        "student_task": source_activity["student_task"],
        "answer_space": source_activity["answer_space"],
        "feedback_record": source_activity["feedback_record"],
    }
    assert teacher_activity["answer_check"] == source_activity["answer_check"]
    assert "answer_check" not in student_activity
    assert "teacher_prompt" not in student_activity
    assert "stuck_support" not in student_activity


def test_example_edits_stay_in_example_data_and_export(api):
    """编辑示例后，导出包含示例数据，通用学习路径和真实学生记录仍为空。"""
    original = api.get("/lesson-plan-examples/default").json()
    original["activities"][0]["student_task"] = "圈出属于集合 A 的元素，并写出判断理由。"

    saved = api.put("/lesson-plan-examples/default", json={
        "title": original["title"],
        "activities": original["activities"],
    })

    assert saved.status_code == 200
    assert saved.json()["activities"][0]["student_task"] == original["activities"][0]["student_task"]
    exported = api.get("/export").json()
    assert exported["goals"] == []
    assert exported["lesson_plan_examples"][0]["id"] == "default"
    assert exported["lesson_plan_examples"][0]["activities"][0]["student_task"] == original["activities"][0]["student_task"]
