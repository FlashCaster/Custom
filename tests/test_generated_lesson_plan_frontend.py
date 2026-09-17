"""票 #3 前端入口：生成只能由教师主动点击，并打开可编辑候选。"""
from pathlib import Path


def test_preparation_page_has_an_explicit_generation_action_and_editable_candidate_view():
    source = (Path(__file__).resolve().parent.parent / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "function renderLessonPlanGeneration" in source
    assert "lesson-plans/generate" in source
    assert "生成可编辑候选" in source
    assert "function renderGeneratedLessonPlan" in source
    assert ".innerHTML =" not in source
