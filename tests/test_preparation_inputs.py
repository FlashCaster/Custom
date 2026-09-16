"""备课票 #2：学生档案、材料读取边界和可核查引用的 API 验收。"""
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
    directory = _BASE / uuid.uuid4().hex
    os.makedirs(directory, exist_ok=True)
    monkeypatch.setattr(store, "DB_PATH", directory / "test.db")
    with TestClient(app) as client:
        yield client
    shutil.rmtree(directory, ignore_errors=True)


def _student_payload(**overrides):
    payload = {
        "name": "小林",
        "grade": "高一",
        "subject": "数学",
        "observed_errors": ["把集合元素和集合本身混淆"],
        "independent_tasks": ["能独立代入一元一次不等式"],
        "school_progress_status": "unknown",
        "school_progress": None,
    }
    payload.update(overrides)
    return payload


def _material_payload(**overrides):
    payload = {
        "title": "必修一函数章节",
        "file_identifier": "math-book.pdf",
        "selected_pages": [12, 13],
        "usage_scope": "只用于函数概念判断和定义域活动",
        "read_pages": [
            {"page": 12, "content": "函数要求定义域内每一个输入恰好对应一个输出。"},
        ],
        "unread_pages": [13],
        "statements": [
            {"topic": "函数定义", "text": "函数要求定义域内每一个输入恰好对应一个输出。", "page": 12},
        ],
    }
    payload.update(overrides)
    return payload


def test_teacher_can_create_and_select_minimal_student_profile(api):
    created = api.post("/students", json=_student_payload())

    assert created.status_code == 201
    student = created.json()
    assert student["school_progress_status"] == "unknown"
    assert student["school_progress"] is None
    assert student["observed_errors"] == ["把集合元素和集合本身混淆"]
    assert api.get("/students").json() == [student]
    assert api.get(f"/students/{student['id']}").json()["independent_tasks"] == ["能独立代入一元一次不等式"]


def test_student_profile_rejects_inference_when_school_progress_is_unknown(api):
    response = api.post("/students", json=_student_payload(school_progress="学校已经讲完函数性质"))

    assert response.status_code == 400
    assert "unknown" in response.json()["detail"]


def test_material_records_unread_pages_and_only_read_content_can_be_cited(api):
    created = api.post("/reference-materials", json=_material_payload())

    assert created.status_code == 201
    material = created.json()
    assert material["unread_pages"] == [13]
    assert material["read_pages"][0]["page"] == 12
    assert material["fallback_paths"] == ["replace_material", "paste_content", "create_original_question"]
    citation = api.post(f"/reference-materials/{material['id']}/citations", json={
        "page": 12,
        "locator": "每一个输入恰好对应一个输出",
    })
    assert citation.status_code == 201
    assert citation.json()["page"] == 12
    unread = api.post(f"/reference-materials/{material['id']}/citations", json={
        "page": 13,
        "locator": "无法读取的内容",
    })
    assert unread.status_code == 400
    assert "未读取" in unread.json()["detail"]


def test_student_material_selection_keeps_teacher_usage_scope(api):
    student = api.post("/students", json=_student_payload()).json()
    material = api.post("/reference-materials", json=_material_payload()).json()

    selected = api.post(f"/students/{student['id']}/reference-materials/{material['id']}/selections", json={
        "selected_pages": [12, 13],
        "usage_scope": "仅核查函数定义；第 13 页不可作引用",
    })

    assert selected.status_code == 201
    assert selected.json()["selected_pages"] == [12, 13]
    listing = api.get(f"/students/{student['id']}/reference-materials/selections")
    assert listing.status_code == 200
    assert listing.json()[0]["material"]["unread_pages"] == [13]


def test_conflicting_read_statements_and_page_numbers_remain_available_for_teacher_choice(api):
    student = api.post("/students", json=_student_payload()).json()
    first = api.post("/reference-materials", json=_material_payload()).json()
    second = api.post("/reference-materials", json=_material_payload(
        title="教辅函数表述",
        file_identifier="workbook.pdf",
        selected_pages=[8],
        read_pages=[{"page": 8, "content": "函数是两个非空数集之间的一种对应关系。"}],
        unread_pages=[],
        statements=[{"topic": "函数定义", "text": "函数是两个非空数集之间的一种对应关系。", "page": 8}],
    )).json()

    statements = api.get("/reference-statements", params={"topic": "函数定义"})
    assert statements.status_code == 200
    assert [(item["material_id"], item["page"]) for item in statements.json()] == [
        (first["id"], 12), (second["id"], 8),
    ]
    choice = api.post(f"/students/{student['id']}/reference-statements/{second['statements'][0]['id']}/choose")
    assert choice.status_code == 200
    assert choice.json()["statement_id"] == second["statements"][0]["id"]
    assert len(api.get("/reference-statements", params={"topic": "函数定义"}).json()) == 2
    exported = api.get("/export").json()
    assert exported["reference_statement_choices"][0]["statement_id"] == second["statements"][0]["id"]


def test_pasted_content_is_explicitly_marked_and_export_keeps_prep_records(api):
    student = api.post("/students", json=_student_payload()).json()
    pasted = api.post("/reference-materials/pasted", json={
        "title": "教师粘贴的课堂讲义",
        "content": "定义域要同时考虑情境限制和表达式限制。",
        "usage_scope": "函数定义域练习",
    })

    assert pasted.status_code == 201
    assert pasted.json()["source_kind"] == "pasted"
    api.post(f"/students/{student['id']}/reference-materials/{pasted.json()['id']}/selections", json={
        "selected_pages": [1], "usage_scope": "本次定义域练习",
    })
    exported = api.get("/export").json()
    assert exported["students"][0]["name"] == "小林"
    assert exported["reference_materials"][0]["source_kind"] == "pasted"
    assert exported["material_selections"][0]["student_id"] == student["id"]
    assert exported["reference_citations"] == []
    assert exported["reference_statement_choices"] == []
