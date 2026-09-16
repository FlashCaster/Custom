"""示例备课稿的领域规则在服务层，而不是 SQLite 存储层。"""
from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

import pytest

from backend import lesson_plans, store


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


def test_default_example_is_initialized_by_service_and_student_page_is_a_safe_projection(db):
    teacher = lesson_plans.get_example("default")
    student = lesson_plans.student_task_page("default")

    assert teacher["label"] == "示例"
    stored = store.list_lesson_plan_examples()
    assert stored[0]["id"] == teacher["id"]
    assert stored[0]["activities"] == teacher["activities"]
    assert "label" not in stored[0]
    assert student["activities"][0] == {
        "id": teacher["activities"][0]["id"],
        "position": 0,
        "title": teacher["activities"][0]["title"],
        "student_task": teacher["activities"][0]["student_task"],
        "answer_space": teacher["activities"][0]["answer_space"],
        "feedback_record": teacher["activities"][0]["feedback_record"],
    }


def test_service_rejects_invalid_activity_shape_before_persisting(db):
    original = lesson_plans.get_example("default")
    invalid = [dict(activity) for activity in original["activities"]]
    invalid[1]["position"] = 3

    with pytest.raises(ValueError, match="连续编号"):
        lesson_plans.update_example("default", original["title"], invalid)

    assert lesson_plans.get_example("default")["activities"] == original["activities"]


def test_service_updates_known_example_and_reports_unknown_example(db):
    original = lesson_plans._DEFAULT_EXAMPLE
    activities = [dict(activity) for activity in original["activities"]]
    activities[0]["student_task"] = "写出集合判断的理由。"

    updated = lesson_plans.update_example("default", original["title"], activities)

    assert updated["activities"][0]["student_task"] == "写出集合判断的理由。"
    assert lesson_plans.get_example("missing") is None
    assert lesson_plans.update_example("missing", "不存在", []) is None
