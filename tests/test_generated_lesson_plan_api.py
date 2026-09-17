"""票 #3：真实备课稿生成 API 的完整入口验收。"""
from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend import store
from backend.main import app, get_llm_client


_BASE = Path(__file__).resolve().parent.parent / "data" / ".test_dbs"


@pytest.fixture
def api(monkeypatch):
    directory = _BASE / uuid.uuid4().hex
    os.makedirs(directory, exist_ok=True)
    monkeypatch.setattr(store, "DB_PATH", directory / "test.db")
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    shutil.rmtree(directory, ignore_errors=True)


def _student(api):
    return api.post("/students", json={
        "name": "小林", "grade": "高一", "subject": "数学", "observed_errors": ["集合条件混淆"],
        "independent_tasks": ["能写出不等式变形理由"], "school_progress_status": "unknown",
        "school_progress": None,
    }).json()


def _material(api, student_id):
    material = api.post("/reference-materials", json={
        "title": "函数讲义", "file_identifier": "function.pdf", "selected_pages": [1],
        "usage_scope": "函数概念", "read_pages": [{"page": 1, "content": "每一个输入恰好对应一个输出。"}],
        "unread_pages": [], "statements": [{"topic": "函数定义", "text": "每一个输入恰好对应一个输出。", "page": 1}],
    }).json()
    api.post(f"/students/{student_id}/reference-materials/{material['id']}/selections", json={
        "selected_pages": [1], "usage_scope": "仅函数概念",
    })
    api.post(f"/students/{student_id}/reference-statements/{material['statements'][0]['id']}/choose")
    return material


def _fake_client(material_id, statement_id):
    basis = [{"material_id": material_id, "page": 1, "locator": "每一个输入恰好对应一个输出"}]
    fields = {"minutes": 15, "material_basis": basis, "selected_statement_ids": [statement_id]}
    payload = {"activities": [
        {**fields, "topic": "sets_inequalities", "defer_if_old_knowledge_weak": False},
        {**fields, "topic": "function_concept", "defer_if_old_knowledge_weak": True},
    ]}
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False)))],
        usage=SimpleNamespace(prompt_tokens=8, completion_tokens=13),
    )
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: response)))


def test_teacher_generates_a_real_candidate_only_by_clicking_the_generation_endpoint(api):
    student = _student(api)
    material = _material(api, student["id"])
    app.dependency_overrides[get_llm_client] = lambda: _fake_client(material["id"], material["statements"][0]["id"])

    generated = api.post(f"/students/{student['id']}/lesson-plans/generate", json={
        "course_objective": "先检查集合与不等式，再视情况进入函数概念", "total_minutes": 120,
        "math_minutes": 80, "old_knowledge_weak": True,
    })

    assert generated.status_code == 201
    plan = generated.json()
    assert plan["usage"]["total_tokens"] == 21
    assert plan["activities"][1]["defer_if_old_knowledge_weak"] is True
    fetched = api.get(f"/lesson-plans/{plan['id']}/teacher-manuscript")
    assert fetched.status_code == 200
    assert fetched.json()["activities"] == plan["activities"]

    plan["title"] = "教师改写的标题"
    plan["activities"][0]["student_task"] = "改写后的学生任务"
    saved = api.put(f"/lesson-plans/{plan['id']}", json={
        "title": plan["title"], "activities": plan["activities"],
    })
    assert saved.status_code == 200
    assert saved.json()["title"] == "教师改写的标题"
    assert saved.json()["activities"][0]["student_task"] == "改写后的学生任务"
