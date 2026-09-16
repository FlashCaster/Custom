"""备课资料前端的关键行为入口保持可发现且使用 DOM 文本节点渲染。"""
from pathlib import Path


APP_JS = Path(__file__).resolve().parent.parent / "frontend" / "app.js"
INDEX_HTML = Path(__file__).resolve().parent.parent / "frontend" / "index.html"


def test_preparation_screen_exposes_student_material_and_fallback_paths_without_html_injection():
    source = APP_JS.read_text(encoding="utf-8")
    markup = INDEX_HTML.read_text(encoding="utf-8")

    assert 'id="btn-preparation-inputs"' in markup
    assert "function enterPreparation()" in source
    assert 'api("/students")' in source
    assert 'api("/reference-materials")' in source
    assert '"/reference-materials/pasted"' in source
    assert "无法读取：第" in source
    assert "新编题" in source
    assert ".innerHTML =" not in source
