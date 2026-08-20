"""G2 占位测试：pytest 能跑通 + 骨架主入口可导入。"""


def test_app_imports_and_has_health():
    from backend.main import app

    assert app is not None
    assert "/health" in {r.path for r in app.routes}
