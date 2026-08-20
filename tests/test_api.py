"""G3-第5步 test_api.py：API 路由 TDD（TestClient + dependency_overrides 注入 fake LLM client）。

2.4 标准用例表（正常 ≥3 组 + 攻击 ≥10 组，八大类每类 ≥1，组合 ≥2）：

| 编号 | 类别 | 输入 | 预期 |
|---|---|---|---|
| T01 | 正常-最小 | POST /goals（interests 缺省）→ GET /goals 回读 | 201 + 列表含新 goal |
| T02 | 正常-典型 | POST generate（fake client 返回合法候选含未知键 + 代码块壳） | 201 draft 完整树，未知键已剔 |
| T03 | 正常-复杂 | quiz 文本答案大小写不敏感 pass；再答错一道 → fail；artifact 全勾 pass | result 正确；attempts 入库；recommended 随历史升降 |
| T04 | 正常-集成 | activate → GET /paths/{id} 为 active；GET progress 当前任务推进正确；GET /export 嵌套含 attempts | 全部一致 |
| T05 | 正常-store新增 | list_paths 按 goal 过滤 / export_all 空库与满库 | 在 test_store.py 覆盖 |
| A01 | 攻击-空数据 | statement 空白 / body 空对象 / checklist 空 | 422 / 422 / 400 |
| A02 | 攻击-极值 | difficulty 0 任务答错 → recommended 0（N0 下限） | 0，不越界 |
| A03 | 攻击-越界 | 不存在 goal/path/task id；quiz answer 索引 99 | 404 / 404 / 404；fail 200 |
| A04 | 攻击-脏数据 | statement 前后空格 / answer "  Rag  " | 保留往返；pass（checker 去空格） |
| A05 | 攻击-特殊字符 | statement 含 SQL 注入串 + emoji + 引号 | 201 后回读一致（参数化） |
| A06 | 攻击-异常格式 | body 非 JSON / answer 传 bool 或对象 | 422 |
| A07 | 攻击-缺失字段 | POST /goals 缺 statement / generate 前 goal 不存在 | 422 / 404 |
| A08 | 攻击-未知结构 | body 多余键 | 忽略（pydantic 默认），200 |
| A09 | 组合1 | 不存在的 goal 上 generate + 断言无 path 残留 | 404 且 store 无新增 path |
| A10 | 组合2 | quiz 坏数据（options 空，直接写库绕过 planner）→ attempts | 400（ValueError 兜底），不 500 |
| A11 | 攻击-类型 | interests 非 list[str] / checklist 含非 bool | 422 |
| A12 | 攻击-超长 | statement 501 字 / interests 11 项 / 单项 101 字 | 422 |
| A13 | 集成-攻击 | fake client 抛 RuntimeError / 返回坏 JSON / 无 key 工厂 | 502 / 400 / 503，进程不崩 |

实现说明：每个用例独立 SQLite（monkeypatch store.DB_PATH，lifespan 幂等 init_db）；
fake client 经 app.dependency_overrides 注入（本文件不碰真实网络/key）；
无 key 分支用 monkeypatch.delenv 保证隔离，只测 503 语义。
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend import store
from backend.main import app

_BASE = Path(__file__).resolve().parent.parent / "data" / ".test_dbs"

_CANDIDATE = {
    "title": "候选路径",
    "extra_key": "应被剔除",
    "stages": [
        {
            "title": "阶段一",
            "unknown": 123,
            "tasks": [
                {"kind": "quiz", "title": "Q1", "brief": "b1", "difficulty": 1,
                 "skills": ["检索"], "junk": "x",
                 "quiz": {"q": "哪项正确？", "options": ["选项A", "选项B"], "answer": 0,
                          "explanation": "解析A", "junk": 9}},
                {"kind": "artifact", "title": "A1", "brief": "b2", "difficulty": 2,
                 "acceptance": ["检查1"], "extra": 3},
            ],
        }
    ],
}
_CANDIDATE_JSON = "```json\n" + json.dumps(_CANDIDATE, ensure_ascii=False) + "\n```"


def _fake_client(content=_CANDIDATE_JSON, exc=None):
    """OpenAI 兼容协议的假 client：create(**kwargs) 返回 choices[0].message.content。"""
    def create(**kwargs):
        if exc is not None:
            raise exc
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def _override_client(client):
    from backend.main import get_llm_client  # 惰性导入：红阶段该符号尚不存在
    app.dependency_overrides[get_llm_client] = lambda: client


@pytest.fixture
def db(monkeypatch):
    """每个用例一个独立 SQLite 库（workspace 内，同 test_store 约定）。"""
    d = _BASE / uuid.uuid4().hex
    os.makedirs(d, exist_ok=True)
    path = d / "test.db"
    yield path
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def api(db, monkeypatch):
    """独立库 + fake client 注入 + lifespan 启动的 TestClient。"""
    monkeypatch.setattr(store, "DB_PATH", db)
    _override_client(_fake_client())
    with TestClient(app) as c:  # with 触发 lifespan → init_db
        yield c
    app.dependency_overrides.clear()


def _mk_quiz(db, gid, difficulty=1, quiz=None):
    quiz = quiz or {"q": "RAG 是什么？", "options": ["Rag", "CNN"], "answer": 0,
                    "explanation": "检索增强生成"}
    return _mk_task(db, gid, {"kind": "quiz", "title": "q", "difficulty": difficulty,
                              "brief": "b", "quiz": quiz, "skills": []})


def _mk_artifact(db, gid, difficulty=2, acceptance=("报告", "清单")):
    return _mk_task(db, gid, {"kind": "artifact", "title": "a", "difficulty": difficulty,
                              "brief": "b", "acceptance": list(acceptance), "skills": []})


def _mk_task(db, gid, task_spec):
    """直接经 store 造任务（绕过 API，供攻击用例构造任意数据）。"""
    pid = store.create_path(gid, "p", stages=[{"title": "s", "tasks": [task_spec]}])
    return store.get_path(pid)["stages"][0]["tasks"][0]


# ---------- 正常功能（≥3 组）----------

def test_create_goal_minimal_and_list(api):
    """T01 正常-最小：interests 缺省 → 201 + 列表回读。"""
    r = api.post("/goals", json={"statement": "学习 LLM 基础"})
    assert r.status_code == 201
    g = r.json()
    assert g["statement"] == "学习 LLM 基础"
    assert g["interests"] == []
    assert isinstance(g["id"], int) and g["created_at"]
    lst = api.get("/goals").json()
    assert [x["id"] for x in lst] == [g["id"]]


def test_generate_candidate_full_tree(api):
    """T02 正常-典型：代码块壳剥离 + 未知键剔除 → 201 draft 完整树。"""
    gid = api.post("/goals", json={"statement": "学 RAG", "interests": ["检索"]}).json()["id"]
    r = api.post(f"/goals/{gid}/paths/generate")
    assert r.status_code == 201
    tree = r.json()
    assert tree["title"] == "候选路径"
    assert tree["status"] == "draft"
    assert "extra_key" not in tree
    stage = tree["stages"][0]
    assert "unknown" not in stage
    quiz_t, art_t = stage["tasks"]
    assert quiz_t["kind"] == "quiz"
    assert "junk" not in quiz_t and "junk" not in quiz_t["quiz"]
    assert quiz_t["quiz"]["options"] == ["选项A", "选项B"]
    assert art_t["kind"] == "artifact"
    assert "extra" not in art_t


def test_attempts_dual_mode_and_recommendation(api, db):
    """T03 正常-复杂：quiz 双模答案 + artifact 清单，attempts 入库，recommended 随历史升降。"""
    gid = api.post("/goals", json={"statement": "学 RAG"}).json()["id"]
    quiz_t = _mk_quiz(db, gid, difficulty=1)
    art_t = _mk_artifact(db, gid, difficulty=2)
    # 1) 文本答案大小写不敏感 → pass；历史 [pass@1] → 保持 1
    r = api.post(f"/tasks/{quiz_t['id']}/attempts", json={"answer": "rag"})
    assert r.status_code == 200
    assert r.json()["result"] == "pass"
    assert r.json()["evidence"] == "检索增强生成"
    assert r.json()["recommended_difficulty"] == 1
    # 2) 答错 → fail；fail → 降级 0
    r = api.post(f"/tasks/{quiz_t['id']}/attempts", json={"answer": "CNN"})
    assert r.json()["result"] == "fail"
    assert r.json()["recommended_difficulty"] == 0
    # 3) 再答对 → pass；恢复 1（最近 fail 已过，保持当前）
    r = api.post(f"/tasks/{quiz_t['id']}/attempts", json={"answer": "RAG"})
    assert r.json()["result"] == "pass"
    assert r.json()["recommended_difficulty"] == 1
    # 4) artifact 全勾 → pass；历史 [pass@2] → 保持 2
    r = api.post(f"/tasks/{art_t['id']}/attempts", json={"checklist": [True, True]})
    assert r.json() == {"result": "pass", "evidence": "全部勾选", "recommended_difficulty": 2}
    # pass/fail 都入库
    assert [a["result"] for a in store.get_attempts(quiz_t["id"])] == ["pass", "fail", "pass"]
    assert [a["result"] for a in store.get_attempts(art_t["id"])] == ["pass"]


def test_activate_progress_export_integration(api):
    """T04 正常-集成：activate（幂等）→ 进度派生推进 → export 嵌套含 attempts。"""
    gid = api.post("/goals", json={"statement": "集成"}).json()["id"]
    pid = api.post(f"/goals/{gid}/paths/generate").json()["id"]
    assert api.post(f"/paths/{pid}/activate").status_code == 200
    assert api.post(f"/paths/{pid}/activate").status_code == 200  # 幂等
    assert api.get(f"/paths/{pid}").json()["status"] == "active"

    tasks = [t for s in api.get(f"/paths/{pid}").json()["stages"] for t in s["tasks"]]
    prog = api.get(f"/paths/{pid}/progress").json()
    assert prog == {"current_task_id": tasks[0]["id"], "current_stage_id": tasks[0]["stage_id"],
                    "completed": 0, "total": 2, "percent": 0}
    # 完成第一个任务 → 当前任务推进
    api.post(f"/tasks/{tasks[0]['id']}/attempts", json={"answer": 0})
    prog = api.get(f"/paths/{pid}/progress").json()
    assert prog["current_task_id"] == tasks[1]["id"]
    assert prog["completed"] == 1 and prog["total"] == 2 and prog["percent"] == 50
    # 全部完成 → current=null、percent=100
    api.post(f"/tasks/{tasks[1]['id']}/attempts", json={"checklist": [True]})
    prog = api.get(f"/paths/{pid}/progress").json()
    assert prog["current_task_id"] is None and prog["current_stage_id"] is None
    assert prog["completed"] == 2 and prog["percent"] == 100
    # export 嵌套含 attempts（按 task 挂载）
    dump = api.get("/export").json()
    d_tasks = [t for s in dump["goals"][0]["paths"][0]["stages"] for t in s["tasks"]]
    assert [a["result"] for a in d_tasks[0]["attempts"]] == ["pass"]
    assert [a["result"] for a in d_tasks[1]["attempts"]] == ["pass"]


# ---------- 攻击与边界（≥10 组）----------

def test_blank_statement_missing_fields_empty_checklist(api, db):
    """A01 攻击-空数据：statement 空白 422；body 空对象 422；artifact 空 checklist → 400。"""
    assert api.post("/goals", json={"statement": "   "}).status_code == 422
    assert api.post("/goals", json={}).status_code == 422
    gid = api.post("/goals", json={"statement": "x"}).json()["id"]
    art_t = _mk_artifact(db, gid)
    r = api.post(f"/tasks/{art_t['id']}/attempts", json={"checklist": []})
    assert r.status_code == 400
    assert "长度" in r.json()["detail"]  # detail 原样带原因


def test_difficulty_zero_fail_floor(api, db):
    """A02 攻击-极值：difficulty 0 任务答错 → recommended 0（N0 下限，不越界）。"""
    gid = api.post("/goals", json={"statement": "x"}).json()["id"]
    quiz_t = _mk_quiz(db, gid, difficulty=0)
    r = api.post(f"/tasks/{quiz_t['id']}/attempts", json={"answer": 99})
    assert r.status_code == 200
    assert r.json()["result"] == "fail"
    assert r.json()["recommended_difficulty"] == 0


def test_nonexistent_ids_and_out_of_range_answer(api, db):
    """A03 攻击-越界：不存在 id 全 404；quiz answer 索引 99 → fail 200（不崩）。"""
    assert api.post("/goals/999/paths/generate").status_code == 404
    assert api.get("/paths/999").status_code == 404
    assert api.post("/paths/999/activate").status_code == 404
    assert api.get("/paths/999/progress").status_code == 404
    assert api.post("/tasks/999/attempts", json={"answer": 0}).status_code == 404
    gid = api.post("/goals", json={"statement": "x"}).json()["id"]
    quiz_t = _mk_quiz(db, gid)
    r = api.post(f"/tasks/{quiz_t['id']}/attempts", json={"answer": 99})
    assert r.status_code == 200
    assert r.json()["result"] == "fail"


def test_whitespace_statement_roundtrip_and_answer_trim(api, db):
    """A04 攻击-脏数据：statement 前后空格原样保留；answer "  Rag  " → pass（checker 去空格）。"""
    r = api.post("/goals", json={"statement": "  前后空格  "})
    assert r.status_code == 201
    gid = r.json()["id"]
    assert store.get_goal(gid)["statement"] == "  前后空格  "  # 往返原样
    quiz_t = _mk_quiz(db, gid)
    r = api.post(f"/tasks/{quiz_t['id']}/attempts", json={"answer": "  Rag  "})
    assert r.json()["result"] == "pass"


def test_special_chars_statement_safe(api):
    """A05 攻击-特殊字符：SQL 注入串 + emoji + 引号 → 201 后回读一致（参数化）。"""
    payload = "'); DROP TABLE goals;-- 😀 '单引号' \"双引号\""
    r = api.post("/goals", json={"statement": payload})
    assert r.status_code == 201
    gid = r.json()["id"]
    assert api.get("/goals").json()[0]["statement"] == payload
    assert store.get_goal(gid)["statement"] == payload
    assert store.list_goals()  # 表仍在、数据完好


def test_non_json_body_and_bad_answer_types(api, db):
    """A06 攻击-异常格式：body 非 JSON 422；answer 传 bool/对象 422。"""
    r = api.post("/goals", content="not a json", headers={"Content-Type": "application/json"})
    assert r.status_code == 422
    gid = api.post("/goals", json={"statement": "x"}).json()["id"]
    quiz_t = _mk_quiz(db, gid)
    assert api.post(f"/tasks/{quiz_t['id']}/attempts", json={"answer": True}).status_code == 422
    assert api.post(f"/tasks/{quiz_t['id']}/attempts",
                    json={"answer": {"a": 1}}).status_code == 422


def test_missing_statement_and_generate_missing_goal(api):
    """A07 攻击-缺失字段：POST /goals 缺 statement 422；generate 前 goal 不存在 404。"""
    assert api.post("/goals", json={"interests": ["x"]}).status_code == 422
    assert api.post("/goals/999/paths/generate").status_code == 404


def test_extra_keys_ignored(api):
    """A08 攻击-未知结构：body 多余键忽略（pydantic 默认），200。"""
    r = api.post("/goals", json={"statement": "x", "interests": [], "hack": 1,
                                 "extra": {"a": 1}})
    assert r.status_code == 201
    g = r.json()
    assert "hack" not in g and "extra" not in g


def test_generate_missing_goal_no_residue(api):
    """A09 组合1：不存在的 goal 上 generate → 404 且 store 无任何残留。"""
    r = api.post("/goals/999/paths/generate")
    assert r.status_code == 404
    assert store.list_goals() == []
    assert store.list_paths() == []


def test_bad_quiz_data_value_error_400(api, db):
    """A10 组合2：options 空（直接写库绕过 planner）→ attempts 400（ValueError 兜底），不 500。"""
    gid = api.post("/goals", json={"statement": "x"}).json()["id"]
    pid = store.create_path(gid, "p")
    sid = store.create_stage(pid, "s")
    conn = sqlite3.connect(str(store.DB_PATH))
    conn.execute("PRAGMA foreign_keys=ON")
    cur = conn.execute(
        "INSERT INTO tasks(stage_id, kind, title, brief, difficulty, quiz, acceptance, skills) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (sid, "quiz", "bad", "", 1,
         json.dumps({"q": "x", "options": [], "answer": 0}), "[]", "[]"))
    tid = cur.lastrowid
    conn.commit()
    conn.close()
    r = api.post(f"/tasks/{tid}/attempts", json={"answer": 0})
    assert r.status_code == 400
    assert "options" in r.json()["detail"]
    assert store.get_attempts(tid) == []  # 判分失败不落库


def test_wrong_types_422(api, db):
    """A11 攻击-类型：interests 非 list[str] / statement 非 str / checklist 含非 bool → 422。"""
    assert api.post("/goals", json={"statement": "x",
                                    "interests": ["ok", 1]}).status_code == 422
    assert api.post("/goals", json={"statement": "x", "interests": "RAG"}).status_code == 422
    assert api.post("/goals", json={"statement": 123}).status_code == 422
    gid = api.post("/goals", json={"statement": "x"}).json()["id"]
    art_t = _mk_artifact(db, gid)
    assert api.post(f"/tasks/{art_t['id']}/attempts",
                    json={"checklist": [True, "x"]}).status_code == 422


def test_overlong_422(api):
    """A12 攻击-超长：statement 501 字 / interests 11 项 / 单项 101 字 → 422。"""
    assert api.post("/goals", json={"statement": "x" * 501}).status_code == 422
    assert api.post("/goals", json={"statement": "x",
                                    "interests": ["i"] * 11}).status_code == 422
    assert api.post("/goals", json={"statement": "x",
                                    "interests": ["y" * 101]}).status_code == 422
    # 边界值本身合法（500 / 10×100）
    r = api.post("/goals", json={"statement": "x" * 500, "interests": ["y" * 100] * 10})
    assert r.status_code == 201


def test_client_failure_modes(api, monkeypatch):
    """A13 集成-攻击：client 异常 502 / 坏 JSON 400 / 无 key 503，进程不崩。"""
    gid = api.post("/goals", json={"statement": "x"}).json()["id"]
    # LLM client 抛异常（网络/API 错）→ 502
    _override_client(_fake_client(exc=RuntimeError("boom")))
    r = api.post(f"/goals/{gid}/paths/generate")
    assert r.status_code == 502
    assert "boom" in r.json()["detail"]
    # LLM 返回坏 JSON → 400（ValueError 兜底）
    _override_client(_fake_client("不是 JSON"))
    r = api.post(f"/goals/{gid}/paths/generate")
    assert r.status_code == 400
    assert "JSON" in r.json()["detail"]
    # 无 key → 503（依赖工厂直挂，无真实网络调用）
    app.dependency_overrides.clear()
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    r = api.post(f"/goals/{gid}/paths/generate")
    assert r.status_code == 503
    assert "DEEPSEEK_API_KEY" in r.json()["detail"]


def test_health(api):
    """G2 遗留 /health 保留。"""
    assert api.get("/health").json() == {"status": "ok"}
