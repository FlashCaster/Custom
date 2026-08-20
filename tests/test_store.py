"""G3-第2步 test_store.py：store 层 TDD（CRUD + 级联 + 并发）。

2.4 标准用例表（正常 ≥3 组 + 攻击 ≥10 组，八大类每类 ≥1，含 ≥2 组合攻击）：

| 编号 | 类别 | 输入 | 预期行为 |
|---|---|---|---|
| T01 | 正常-最小 | create_goal 仅 statement | 返回 id；get_goal 字段正确、interests=[] |
| T02 | 正常-典型 | create_path 嵌套 stages+tasks(quiz/artifact) | get_path 嵌套结构完整、quiz 反序列化为 dict |
| T03 | 正常-复杂 | 多实体 + 多条 attempt | list_goals/get_stage_tasks/get_attempts 正确 |
| T04 | 级联 | 删除 goal / path / stage | 子表记录全部级联清空 |
| A01 | 攻击-空数据 | 空/纯空白 statement | ValueError |
| A02 | 攻击-极值 | difficulty 0/3/-1/4 | 0、3 通过；-1、4 拒绝（Python + DB CHECK 双层） |
| A03 | 攻击-脏数据 | statement 前后空格 | 原样保留往返；纯空白拒绝 |
| A04 | 攻击-特殊字符 | SQL 注入串 + 引号 + 换行 | 参数化往返、库未坏、数据完整 |
| A05 | 攻击-异常格式 | 非法 status/result/kind | ValueError |
| A06 | 攻击-嵌套边界 | quiz 嵌套 options 含特殊字符 | 反序列化完全一致 |
| A07 | 攻击-异常文件 | 多级父目录 / 目录当库 | 自动建目录成功；目录路径报错 |
| A08 | 攻击-缺失字段 | 省略可选字段 | 默认值生效 |
| A09 | 组合1 | 注入+emoji+超长 statement | 往返一致、无异常 |
| A10 | 组合2 | 嵌套+特殊字符+空 acceptance+级联 | 全清、无残留 |
| A11 | 攻击-缺失字段(外键) | 不存在的 goal/stage/task 父 id | IntegrityError |
| A12 | 攻击-异常格式(类型) | statement 非 str / interests 非 list | ValueError |
| T05 | 正常-store新增 | list_paths 按 goal 过滤 / export_all 空库与满库 | 结构正确 |
| C01 | 并发 | 12 线程写 attempts | 12 条全部入库、无丢失 |
| C02 | 并发 | 8 线程建 goal | id 唯一、数量正确 |
| U01 | G3-6 正常-最小 | update_path 仅换 title（stages 原样非空） | 树更新、status 仍 draft |
| U02 | G3-6 正常-典型 | 全量替换 2 stages 3 tasks（已有 attempts） | 新树正确、旧 attempts 级联清空零残留 |
| U03 | G3-6 原子性 | 替换中途失败（第二 stage 坏 kind） | ValueError，旧树原样无恙 |
| U04 | G3-6 攻击 | 不存在 path / title 空白 / stages 非 list | ValueError |
| U05 | G3-6 攻击-特殊字符 | title 注入串 + emoji + 引号 | 往返一致（参数化） |
| U06 | G3-6 边界/职责 | 空 stages / active 状态更新 | store 层允许（清树/不查 status）；非空门在 API 层 |
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import threading
import uuid
from pathlib import Path

import pytest

from backend import store

# DSH 沙箱拦截 tempfile.mkdtemp（pytest 的 tmp_path 依赖它）→ 用 workspace 内普通目录自建
_BASE = Path(__file__).resolve().parent.parent / "data" / ".test_dbs"


@pytest.fixture
def db():
    """每个用例一个独立的 SQLite 数据库（workspace 内，绕过沙箱对 tempfile 的拦截）。"""
    d = _BASE / uuid.uuid4().hex
    os.makedirs(d, exist_ok=True)
    path = d / "test.db"
    store.init_db(path)
    yield path
    shutil.rmtree(d, ignore_errors=True)


def _quiz(**over):
    base = {"q": "什么是 RAG？", "options": ["检索增强生成", "随机森林", "梯度下降"],
            "answer": 0, "explanation": "RAG = Retrieval-Augmented Generation"}
    base.update(over)
    return base


def _mk_goal(db, statement="学习 FastAPI", interests=None):
    return store.create_goal(statement, interests=interests, path=db)


def _mk_full_path(db, goal_id, stage_overrides=None):
    """建一条含 quiz + artifact 任务的路径，返回 (path_id, task_ids_by_kind)。"""
    stages = [
        {"title": "阶段1", "tasks": [
            {"kind": "quiz", "title": "quiz1", "difficulty": 1, "brief": "b1",
             "quiz": _quiz(), "acceptance": [], "skills": ["prompt"]},
            {"kind": "artifact", "title": "art1", "difficulty": 2, "brief": "b2",
             "acceptance": ["产出报告"], "skills": ["writing"]},
        ]},
        {"title": "阶段2", "tasks": [
            {"kind": "quiz", "title": "quiz2", "difficulty": 3, "brief": "b3",
             "quiz": _quiz(q="MCP 全称？"), "acceptance": [], "skills": []},
        ]},
    ]
    if stage_overrides:
        stages = stage_overrides(stages)
    pid = store.create_path(goal_id, "AI 工程师路径", stages=stages, path=db)
    path = store.get_path(pid, path=db)
    tasks = [t for s in path["stages"] for t in s["tasks"]]
    return pid, tasks


# ---------- init / 连接 ----------

def test_init_db_idempotent_and_foreign_keys_enabled(db):
    store.init_db(db)  # 二次调用不报错
    conn = store.get_conn(db)
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"goals", "paths", "stages", "tasks", "attempts"} <= tables
    conn.close()


# ---------- 正常功能（≥3 组）----------

def test_create_and_get_goal_minimal(db):
    """T01 正常-最小。"""
    gid = _mk_goal(db)
    assert isinstance(gid, int)
    g = store.get_goal(gid, path=db)
    assert g["statement"] == "学习 FastAPI"
    assert g["interests"] == []
    assert g["created_at"]


def test_create_path_nested_roundtrip(db):
    """T02 正常-典型：嵌套 stages+tasks 落库，quiz 反序列化为 dict。"""
    gid = _mk_goal(db)
    pid, tasks = _mk_full_path(db, gid)
    assert isinstance(pid, int)
    path = store.get_path(pid, path=db)
    assert path["title"] == "AI 工程师路径"
    assert path["status"] == "draft"
    assert [s["title"] for s in path["stages"]] == ["阶段1", "阶段2"]
    quiz_task = path["stages"][0]["tasks"][0]
    assert quiz_task["kind"] == "quiz"
    assert isinstance(quiz_task["quiz"], dict)
    assert quiz_task["quiz"]["answer"] == 0
    assert quiz_task["skills"] == ["prompt"]
    artifact = path["stages"][0]["tasks"][1]
    assert artifact["kind"] == "artifact"
    assert artifact["quiz"] is None
    assert artifact["acceptance"] == ["产出报告"]


def test_complex_multi_entity_and_listing(db):
    """T03 正常-复杂：多 goal/path/task + 多条 attempt，列表与按 id 归属正确。"""
    g1 = _mk_goal(db, "学 A", ["RAG"])
    g2 = _mk_goal(db, "学 B", ["Agent"])
    _, tasks1 = _mk_full_path(db, g1)
    _, tasks2 = _mk_full_path(db, g2)
    for t in tasks1:
        store.record_attempt(t["id"], 1, "pass", "ok", path=db)
    goals = store.list_goals(path=db)
    assert [g["id"] for g in goals] == [g1, g2]
    assert goals[0]["interests"] == ["RAG"]
    # get_stage_tasks 只返回本阶段任务
    path2 = store.get_path(store.get_goal(g2, path=db)["id"], path=db)  # noqa: F841
    s1_tasks = store.get_stage_tasks(tasks1[0]["stage_id"], path=db)
    assert len(s1_tasks) == 2
    # 每条 attempt 可独立取回
    assert len(store.get_attempts(tasks1[0]["id"], path=db)) == 1


# ---------- 级联 ----------

def test_cascade_delete_goal(db):
    """T04 级联：删 goal → paths/stages/tasks/attempts 全清。"""
    gid = _mk_goal(db)
    pid, tasks = _mk_full_path(db, gid)
    store.record_attempt(tasks[0]["id"], 1, "pass", path=db)
    with store.get_conn(db) as conn:
        conn.execute("DELETE FROM goals WHERE id=?", (gid,))
        conn.commit()
    assert store.get_goal(gid, path=db) is None
    assert store.get_path(pid, path=db) is None
    assert store.get_attempts(tasks[0]["id"], path=db) == []


def test_cascade_delete_path_and_stage(db):
    gid = _mk_goal(db)
    pid, tasks = _mk_full_path(db, gid)
    with store.get_conn(db) as conn:
        conn.execute("DELETE FROM paths WHERE id=?", (pid,))
        conn.commit()
    for t in tasks:
        assert store.get_task(t["id"], path=db) is None
    assert store.get_path(pid, path=db) is None


# ---------- 攻击与边界（≥10 组）----------

def test_empty_statement_rejected(db):
    """A01 空数据。"""
    with pytest.raises(ValueError):
        store.create_goal("", path=db)
    with pytest.raises(ValueError):
        store.create_goal("   ", path=db)


def test_empty_collections_roundtrip(db):
    """A01 空数据：空集合返回空列表而非报错。"""
    gid = _mk_goal(db)
    pid = store.create_path(gid, "空路径", path=db)
    assert store.get_path(pid, path=db)["stages"] == []
    stage_id = store.create_stage(pid, "空阶段", path=db)
    assert store.get_stage_tasks(stage_id, path=db) == []
    _, tasks = _mk_full_path(db, gid)
    assert store.get_attempts(tasks[0]["id"], path=db) == []


def test_difficulty_bounds(db):
    """A02 极值：0/3 通过，-1/4 拒绝；DB CHECK 兜底。"""
    gid = _mk_goal(db)
    pid = store.create_path(gid, "p", stages=[
        {"title": "s", "tasks": [{"kind": "quiz", "title": "t", "difficulty": 3,
                                  "quiz": _quiz()}]}], path=db)
    task = store.get_path(pid, path=db)["stages"][0]["tasks"][0]
    assert task["difficulty"] == 3
    stage_id = task["stage_id"]
    store.create_task(stage_id, "quiz", "d0", 0, quiz=_quiz(), path=db)  # 0 边界通过
    with pytest.raises(ValueError):
        store.create_task(stage_id, "quiz", "d4", 4, quiz=_quiz(), path=db)
    with pytest.raises(ValueError):
        store.create_task(stage_id, "quiz", "neg", -1, quiz=_quiz(), path=db)
    # DB 层 CHECK 兜底（绕过 Python 校验直接写）
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys=ON")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO tasks(stage_id, kind, title, difficulty) VALUES(?,?,?,?)",
                     (stage_id, "quiz", "bad", 4))
    conn.close()


def test_whitespace_statement_handling(db):
    """A03 脏数据：前后空格原样保留；纯空白拒绝。"""
    gid = store.create_goal("  前后空格  ", path=db)
    assert store.get_goal(gid, path=db)["statement"] == "  前后空格  "


def test_sql_injection_and_special_chars_safe(db):
    """A04 特殊字符：注入串 + 引号 + 换行，参数化往返，库未坏。"""
    payload = "'); DROP TABLE goals;-- \n 'quoted' \"double\""
    gid = store.create_goal(payload, ["x' OR 1=1 --"], path=db)
    assert store.get_goal(gid, path=db)["statement"] == payload
    assert store.get_goal(gid, path=db)["interests"] == ["x' OR 1=1 --"]
    assert store.list_goals(path=db)[0]["id"] == gid  # 表仍在、数据完好


def test_invalid_enum_values_rejected(db):
    """A05 异常格式：非法 status/result/kind。"""
    gid = _mk_goal(db)
    pid, tasks = _mk_full_path(db, gid)
    with pytest.raises(ValueError):
        store.set_path_status(pid, "banana", path=db)
    with pytest.raises(ValueError):
        store.record_attempt(tasks[0]["id"], 1, "maybe", path=db)
    with pytest.raises(ValueError):
        store.create_task(tasks[0]["stage_id"], "essay", "t", 1, path=db)


def test_quiz_nested_json_roundtrip(db):
    """A06 嵌套边界：quiz options 含特殊字符 + 多字段，反序列化一致。"""
    gid = _mk_goal(db)
    q = _quiz(options=["a'b\"", "emoji 😀", "换行\n\t"], answer=2, explanation="x'--")
    pid = store.create_path(gid, "p", stages=[
        {"title": "s", "tasks": [{"kind": "quiz", "title": "t", "difficulty": 2,
                                  "quiz": q, "acceptance": ["验收1", "验收2"],
                                  "skills": ["a", "b", "c"]}]}], path=db)
    t = store.get_path(pid, path=db)["stages"][0]["tasks"][0]
    assert t["quiz"] == q
    assert t["acceptance"] == ["验收1", "验收2"]
    assert t["skills"] == ["a", "b", "c"]


def test_file_path_edge_cases(db):
    """A07 异常文件：多级父目录自动创建；目录当库报错。"""
    base = Path(db).parent
    deep = base / "a" / "b" / "deep.db"
    store.init_db(deep)
    assert deep.exists()
    assert store.list_goals(path=deep) == []
    with pytest.raises(sqlite3.OperationalError):
        store.init_db(base)  # base 是已存在目录


def test_missing_optional_fields_defaults(db):
    """A08 缺失字段：省略可选字段走默认值。"""
    gid = store.create_goal("s", path=db)  # interests 缺省
    assert store.get_goal(gid, path=db)["interests"] == []
    pid = store.create_path(gid, "t", path=db)  # stages 缺省
    assert store.get_path(pid, path=db)["stages"] == []
    stage_id = store.create_stage(pid, "s", path=db)
    tid = store.create_task(stage_id, "artifact", "a", 1, path=db)  # brief/acceptance/skills 缺省
    t = store.get_task(tid, path=db)
    assert t["brief"] == ""
    assert t["acceptance"] == []
    assert t["skills"] == []
    assert t["quiz"] is None


def test_combo_injection_unicode_long(db):
    """A09 组合1：注入 + emoji + 换行 + 超长 statement。"""
    payload = ("'; DROP TABLE goals;-- " + "😀🚀" * 50 + "\n\t" + "x" * 9000)
    gid = store.create_goal(payload, path=db)
    assert store.get_goal(gid, path=db)["statement"] == payload
    assert store.list_goals(path=db)  # 库仍可用


def test_combo_nested_special_chars_empty_acceptance_cascade(db):
    """A10 组合2：嵌套 + 特殊字符 + 空 acceptance + 级联删除。"""
    gid = _mk_goal(db)
    q = _quiz(q="x'; DROP TABLE tasks;--", options=["😀", "\n"], answer=0, explanation="e")
    pid = store.create_path(gid, "p", stages=[
        {"title": "s1", "tasks": [
            {"kind": "quiz", "title": "tq", "difficulty": 1, "quiz": q,
             "acceptance": [], "skills": []},
        ]},
        {"title": "s2", "tasks": [
            {"kind": "artifact", "title": "ta", "difficulty": 0,
             "acceptance": ["a'"], "skills": ["s"]},
        ]},
    ], path=db)
    tasks = [t for s in store.get_path(pid, path=db)["stages"] for t in s["tasks"]]
    store.record_attempt(tasks[0]["id"], 1, "pass", "e'", path=db)
    with store.get_conn(db) as conn:
        conn.execute("DELETE FROM goals WHERE id=?", (gid,))
        conn.commit()
    for t in tasks:
        assert store.get_task(t["id"], path=db) is None
        assert store.get_attempts(t["id"], path=db) == []


def test_foreign_key_missing_parent_rejected(db):
    """A11 缺失字段(外键)：不存在的父 id → IntegrityError。"""
    with pytest.raises(sqlite3.IntegrityError):
        store.create_path(999, "orphan path", path=db)
    gid = _mk_goal(db)
    pid = store.create_path(gid, "p", path=db)
    with pytest.raises(sqlite3.IntegrityError):
        store.create_stage(999, "orphan stage", path=db)
    with pytest.raises(sqlite3.IntegrityError):
        store.create_task(999, "quiz", "orphan task", 1, quiz=_quiz(), path=db)
    with pytest.raises(sqlite3.IntegrityError):
        store.record_attempt(999, 1, "pass", path=db)


def test_type_validation_rejected(db):
    """A12 异常格式(类型)：statement 非 str / interests 非 list。"""
    with pytest.raises(ValueError):
        store.create_goal(123, path=db)
    with pytest.raises(ValueError):
        store.create_goal("s", interests="RAG", path=db)
    with pytest.raises(ValueError):
        store.create_goal("s", interests=["ok", 1], path=db)


def test_set_path_status_and_not_found(db):
    """status 更新 + 不存在的 path 报错。"""
    gid = _mk_goal(db)
    pid = store.create_path(gid, "p", path=db)
    store.set_path_status(pid, "active", path=db)
    assert store.get_path(pid, path=db)["status"] == "active"
    store.set_path_status(pid, "done", path=db)
    assert store.get_path(pid, path=db)["status"] == "done"
    with pytest.raises(ValueError):
        store.set_path_status(999, "active", path=db)


# ---------- 并发 ----------

def test_concurrent_attempts_no_lost_writes(db):
    """C01 并发：12 线程写同一 task 的 attempts，无丢失。"""
    gid = _mk_goal(db)
    _, tasks = _mk_full_path(db, gid)
    task_id = tasks[0]["id"]
    n = 12
    barrier = threading.Barrier(n)
    errors = []

    def worker(i):
        try:
            barrier.wait()
            store.record_attempt(task_id, i % 4, "pass", f"ev-{i}", path=db)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    attempts = store.get_attempts(task_id, path=db)
    assert len(attempts) == n
    assert {a["evidence"] for a in attempts} == {f"ev-{i}" for i in range(n)}


def test_concurrent_create_goal_unique_ids(db):
    """C02 并发：8 线程建 goal，id 唯一、数量正确。"""
    n = 8
    barrier = threading.Barrier(n)
    ids = []
    lock = threading.Lock()

    def worker(i):
        barrier.wait()
        gid = store.create_goal(f"goal-{i}", path=db)
        with lock:
            ids.append(gid)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(ids)) == n
    assert len(store.list_goals(path=db)) == n


# ---------- G3-第5步新增：list_paths / export_all ----------

def test_list_paths_all_and_filter_by_goal(db):
    """T05 list_paths：无参返回全部（嵌套完整树，同 get_path 结构）；按 goal 过滤只回本 goal。"""
    g1 = _mk_goal(db, "学 A")
    g2 = _mk_goal(db, "学 B")
    p1, _ = _mk_full_path(db, g1)
    p2, _ = _mk_full_path(db, g2)
    all_paths = store.list_paths(path=db)
    assert {p["id"] for p in all_paths} == {p1, p2}
    for p in all_paths:
        assert set(p) == {"id", "goal_id", "title", "status", "stages"}
        assert p["stages"] and p["stages"][0]["tasks"]
    mine = store.list_paths(g1, path=db)
    assert [p["id"] for p in mine] == [p1]
    assert [s["title"] for s in mine[0]["stages"]] == ["阶段1", "阶段2"]
    assert store.list_paths(999, path=db) == []  # 不存在的 goal → 空


def test_export_all_empty_db(db):
    """T05 export_all 空库：goals 为空列表。"""
    assert store.export_all(path=db) == {"goals": []}


def test_export_all_nested_with_attempts(db):
    """T05 export_all 满库：goals→paths→stages→tasks→attempts 嵌套，attempts 按 task 挂载。"""
    g1 = _mk_goal(db, "学 A", ["RAG"])
    g2 = _mk_goal(db, "学 B")
    p1, tasks1 = _mk_full_path(db, g1)
    store.record_attempt(tasks1[0]["id"], 1, "pass", "ok1", path=db)
    store.record_attempt(tasks1[0]["id"], 0, "fail", "ok2", path=db)
    p2, tasks2 = _mk_full_path(db, g2)
    store.record_attempt(tasks2[-1]["id"], 3, "pass", "ok3", path=db)
    g3 = _mk_goal(db, "学 C")  # 无 path 的 goal

    dump = store.export_all(path=db)
    assert [g["id"] for g in dump["goals"]] == [g1, g2, g3]

    g1d = dump["goals"][0]
    assert g1d["statement"] == "学 A"
    assert g1d["interests"] == ["RAG"]
    assert [p["id"] for p in g1d["paths"]] == [p1]
    tasks = [t for s in g1d["paths"][0]["stages"] for t in s["tasks"]]
    assert [a["result"] for a in tasks[0]["attempts"]] == ["pass", "fail"]
    assert tasks[0]["attempts"][0]["evidence"] == "ok1"
    assert tasks[-1]["attempts"] == []  # 无 attempts 的任务也有空列表

    g2d = dump["goals"][1]
    assert [p["id"] for p in g2d["paths"]] == [p2]
    g2_tasks = [t for s in g2d["paths"][0]["stages"] for t in s["tasks"]]
    assert [a["result"] for a in g2_tasks[-1]["attempts"]] == ["pass"]

    assert dump["goals"][2]["paths"] == []  # 无 path 的 goal


# ---------- G3-第6步新增：update_path（候选修改落地，单事务全量替换） ----------

def _spec_stages():
    """update_path 入参规格（与 create_path 的 stages 同形）：1 stage 2 tasks。"""
    return [
        {"title": "规格阶段", "tasks": [
            {"kind": "quiz", "title": "sq1", "difficulty": 1, "brief": "sb1",
             "quiz": _quiz(), "acceptance": [], "skills": ["prompt"]},
            {"kind": "artifact", "title": "sa1", "difficulty": 2, "brief": "sb2",
             "acceptance": ["规格验收"], "skills": []},
        ]},
    ]


def _alt_stages():
    """全量替换载荷：2 stages 3 tasks（quiz×2 + artifact×1）。"""
    return [
        {"title": "新阶段1", "tasks": [
            {"kind": "quiz", "title": "nq1", "difficulty": 0, "brief": "nb1",
             "quiz": _quiz(q="新问题？", answer=1), "acceptance": [], "skills": []},
            {"kind": "artifact", "title": "na1", "difficulty": 1, "brief": "nb2",
             "acceptance": ["新验收1", "新验收2"], "skills": ["new"]},
        ]},
        {"title": "新阶段2", "tasks": [
            {"kind": "quiz", "title": "nq2", "difficulty": 3, "brief": "nb3",
             "quiz": _quiz(q="另一题？", options=["仅A"], answer=0), "acceptance": [], "skills": []},
        ]},
    ]


def test_update_path_title_only_keeps_tree_shape(db):
    """U01 正常-最小：仅换 title（stages 原样非空全量提交）→ title 更新、status 仍 draft、树形不变。"""
    gid = _mk_goal(db)
    pid = store.create_path(gid, "旧标题", stages=_spec_stages(), path=db)
    before = store.get_path(pid, path=db)
    store.update_path(pid, "新标题", _spec_stages(), path=db)
    after = store.get_path(pid, path=db)
    assert after["title"] == "新标题"
    assert after["status"] == "draft"
    assert [s["title"] for s in after["stages"]] == [s["title"] for s in before["stages"]]
    assert [[t["title"] for t in s["tasks"]] for s in after["stages"]] == \
           [[t["title"] for t in s["tasks"]] for s in before["stages"]]


def test_update_path_full_replace_clears_old_attempts(db):
    """U02 正常-典型：全量替换 → 新树正确；旧 tasks/attempts 级联清空、attempts 表零残留。"""
    gid = _mk_goal(db)
    pid, old_tasks = _mk_full_path(db, gid)
    for t in old_tasks:
        store.record_attempt(t["id"], t["difficulty"], "pass", "old", path=db)
    store.update_path(pid, "替换后路径", _alt_stages(), path=db)
    after = store.get_path(pid, path=db)
    assert after["title"] == "替换后路径"
    assert [s["title"] for s in after["stages"]] == ["新阶段1", "新阶段2"]
    tasks = [t for s in after["stages"] for t in s["tasks"]]
    assert [t["kind"] for t in tasks] == ["quiz", "artifact", "quiz"]
    assert tasks[1]["acceptance"] == ["新验收1", "新验收2"]
    for t in old_tasks:
        assert store.get_task(t["id"], path=db) is None
    conn = store.get_conn(db)
    assert conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0
    conn.close()


def test_update_path_atomic_rollback_on_bad_stage(db):
    """U03 原子性：替换中途失败（第二 stage 坏 kind）→ ValueError，旧树与旧 attempts 原样无恙。"""
    gid = _mk_goal(db)
    pid, tasks = _mk_full_path(db, gid)
    store.record_attempt(tasks[0]["id"], 1, "pass", "keep", path=db)
    bad = [{"title": "新阶段", "tasks": [
                {"kind": "quiz", "title": "ok", "difficulty": 1, "quiz": _quiz()}]},
           {"title": "坏阶段", "tasks": [{"kind": "essay", "title": "bad", "difficulty": 1}]}]
    with pytest.raises(ValueError):
        store.update_path(pid, "不会成功", bad, path=db)
    after = store.get_path(pid, path=db)
    assert after["title"] == "AI 工程师路径"  # 旧标题未动
    assert [s["title"] for s in after["stages"]] == ["阶段1", "阶段2"]  # 旧树无恙
    assert store.get_attempts(tasks[0]["id"], path=db)[0]["evidence"] == "keep"


def test_update_path_not_found_and_invalid_args(db):
    """U04 攻击：不存在 path / title 空白 / stages 非 list → ValueError。"""
    gid = _mk_goal(db)
    pid, _ = _mk_full_path(db, gid)
    with pytest.raises(ValueError):
        store.update_path(999, "t", _spec_stages(), path=db)
    with pytest.raises(ValueError):
        store.update_path(pid, "   ", _spec_stages(), path=db)
    with pytest.raises(ValueError):
        store.update_path(pid, "t", "not a list", path=db)


def test_update_path_special_chars_roundtrip(db):
    """U05 攻击-特殊字符：title 注入串 + emoji + 引号 → 往返一致（参数化），库完好。"""
    gid = _mk_goal(db)
    pid, _ = _mk_full_path(db, gid)
    payload = "'); DROP TABLE paths;-- 😀 '单引号' \"双引号\""
    store.update_path(pid, payload, _spec_stages(), path=db)
    assert store.get_path(pid, path=db)["title"] == payload
    assert store.list_paths(path=db)  # 表仍在、数据完好


def test_update_path_empty_stages_and_status_not_gated(db):
    """U06 边界/职责：空 stages store 层允许（清树，与 create_path 一致；非空门在 API 层 400）；
    store 不查 status（draft 门在 API 层 409），active 路径同样可更新且 status 不变。"""
    gid = _mk_goal(db)
    pid, tasks = _mk_full_path(db, gid)
    store.set_path_status(pid, "active", path=db)
    store.update_path(pid, "空树", [], path=db)
    after = store.get_path(pid, path=db)
    assert after["stages"] == []
    assert after["status"] == "active"
    for t in tasks:
        assert store.get_task(t["id"], path=db) is None
