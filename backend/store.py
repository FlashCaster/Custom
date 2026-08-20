"""SQLite 存储层（sqlite3 标准库）：CRUD，全参数化。

G3 第 2 步：schema 建表 + 索引 + 外键级联 + CRUD。
约定：所有 get_* 返回 dict（JSON 字段已反序列化）；找不到返回 None；
非法输入抛 ValueError；外键缺失抛 sqlite3.IntegrityError。
每个 CRUD 末尾可传 path 覆盖数据库位置（默认 data/custom.db）。
"""
from __future__ import annotations

import contextlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "custom.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    statement TEXT NOT NULL,
    interests TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS paths (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','active','done'))
);
CREATE TABLE IF NOT EXISTS stages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path_id INTEGER NOT NULL REFERENCES paths(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stage_id INTEGER NOT NULL REFERENCES stages(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('quiz','artifact')),
    title TEXT NOT NULL,
    brief TEXT NOT NULL DEFAULT '',
    difficulty INTEGER NOT NULL CHECK (difficulty BETWEEN 0 AND 3),
    quiz TEXT,
    acceptance TEXT NOT NULL DEFAULT '[]',
    skills TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    ts TEXT NOT NULL,
    difficulty INTEGER NOT NULL CHECK (difficulty BETWEEN 0 AND 3),
    result TEXT NOT NULL CHECK (result IN ('pass','fail')),
    evidence TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_paths_goal ON paths(goal_id);
CREATE INDEX IF NOT EXISTS idx_stages_path ON stages(path_id);
CREATE INDEX IF NOT EXISTS idx_tasks_stage ON tasks(stage_id);
CREATE INDEX IF NOT EXISTS idx_attempts_task ON attempts(task_id);
"""


def init_db(path: Path = DB_PATH) -> None:
    """初始化 schema：建表 + 索引（幂等）。父目录不存在则自动创建。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.closing(get_conn(path)) as conn:
        conn.executescript(_SCHEMA)
        conn.commit()


def get_conn(path: Path = DB_PATH) -> sqlite3.Connection:
    """返回连接：row_factory=Row + 外键开启 + busy_timeout（并发写入等待）。"""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


@contextlib.contextmanager
def _conn(path: Path | None):
    conn = get_conn(DB_PATH if path is None else path)
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------- 校验辅助 ----------

def _require_nonempty_str(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} 必须是非空字符串")
    return value


def _require_difficulty(d: int) -> int:
    if isinstance(d, bool) or not isinstance(d, int) or not 0 <= d <= 3:
        raise ValueError("difficulty 必须是 0-3 的整数")
    return d


def _require_str_list(value, name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
        raise ValueError(f"{name} 必须是 str 列表")
    return value


# ---------- goals ----------

def create_goal(statement: str, interests: list[str] | None = None, path: Path | None = None) -> int:
    _require_nonempty_str(statement, "statement")
    interests = _require_str_list(interests, "interests")
    created_at = datetime.now(timezone.utc).isoformat()
    with _conn(path) as conn:
        cur = conn.execute(
            "INSERT INTO goals(statement, interests, created_at) VALUES(?,?,?)",
            (statement, json.dumps(interests, ensure_ascii=False), created_at),
        )
        return cur.lastrowid


def _goal_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "statement": row["statement"],
        "interests": json.loads(row["interests"]),
        "created_at": row["created_at"],
    }


def get_goal(goal_id: int, path: Path | None = None) -> dict | None:
    with _conn(path) as conn:
        row = conn.execute("SELECT * FROM goals WHERE id=?", (goal_id,)).fetchone()
    return _goal_to_dict(row) if row else None


def list_goals(path: Path | None = None) -> list[dict]:
    with _conn(path) as conn:
        rows = conn.execute("SELECT * FROM goals ORDER BY id").fetchall()
    return [_goal_to_dict(r) for r in rows]


# ---------- paths / stages / tasks ----------

def _insert_stage(conn: sqlite3.Connection, path_id: int, title: str, position: int | None) -> int:
    _require_nonempty_str(title, "title")
    if position is None:
        row = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS n FROM stages WHERE path_id=?", (path_id,)
        ).fetchone()
        position = row["n"]
    cur = conn.execute(
        "INSERT INTO stages(path_id, title, position) VALUES(?,?,?)", (path_id, title, position)
    )
    return cur.lastrowid


def _insert_task(conn: sqlite3.Connection, stage_id: int, kind: str, title: str,
                 difficulty: int, brief: str = "", quiz: dict | None = None,
                 acceptance: list[str] | None = None, skills: list[str] | None = None) -> int:
    _require_nonempty_str(title, "title")
    if kind not in ("quiz", "artifact"):
        raise ValueError("kind 必须是 quiz 或 artifact")
    _require_difficulty(difficulty)
    acceptance = _require_str_list(acceptance, "acceptance")
    skills = _require_str_list(skills, "skills")
    if kind == "quiz":
        if not isinstance(quiz, dict):
            raise ValueError("quiz 任务必须提供 dict 类型的 quiz")
        quiz_json = json.dumps(quiz, ensure_ascii=False)
    else:
        quiz_json = None
    cur = conn.execute(
        "INSERT INTO tasks(stage_id, kind, title, brief, difficulty, quiz, acceptance, skills) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (stage_id, kind, title, brief, difficulty, quiz_json,
         json.dumps(acceptance, ensure_ascii=False), json.dumps(skills, ensure_ascii=False)),
    )
    return cur.lastrowid


def create_path(goal_id: int, title: str, stages: list[dict] | None = None,
                path: Path | None = None) -> int:
    """建 path；stages 可选嵌套 [{title, tasks:[...]}]，一次事务落库。"""
    _require_nonempty_str(title, "title")
    if stages is None:
        stages = []
    if not isinstance(stages, list):
        raise ValueError("stages 必须是 list")
    with _conn(path) as conn:
        cur = conn.execute(
            "INSERT INTO paths(goal_id, title, status) VALUES(?,?, 'draft')", (goal_id, title)
        )
        pid = cur.lastrowid
        for st in stages:
            if not isinstance(st, dict):
                raise ValueError("每个 stage 必须是 dict")
            sid = _insert_stage(conn, pid, st.get("title", ""), None)
            for t in st.get("tasks", []):
                _insert_task(conn, sid, **t)
        return pid


def create_stage(path_id: int, title: str, position: int | None = None,
                 path: Path | None = None) -> int:
    with _conn(path) as conn:
        return _insert_stage(conn, path_id, title, position)


def create_task(stage_id: int, kind: str, title: str, difficulty: int, brief: str = "",
                quiz: dict | None = None, acceptance: list[str] | None = None,
                skills: list[str] | None = None, path: Path | None = None) -> int:
    with _conn(path) as conn:
        return _insert_task(conn, stage_id, kind, title, difficulty, brief, quiz, acceptance, skills)


def set_path_status(path_id: int, status: str, path: Path | None = None) -> None:
    if status not in ("draft", "active", "done"):
        raise ValueError("status 必须是 draft/active/done")
    with _conn(path) as conn:
        cur = conn.execute("UPDATE paths SET status=? WHERE id=?", (status, path_id))
        if cur.rowcount == 0:
            raise ValueError(f"path {path_id} 不存在")


def _task_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "stage_id": row["stage_id"],
        "kind": row["kind"],
        "title": row["title"],
        "brief": row["brief"],
        "difficulty": row["difficulty"],
        "quiz": json.loads(row["quiz"]) if row["quiz"] else None,
        "acceptance": json.loads(row["acceptance"]),
        "skills": json.loads(row["skills"]),
    }


def get_path(path_id: int, path: Path | None = None) -> dict | None:
    with _conn(path) as conn:
        prow = conn.execute("SELECT * FROM paths WHERE id=?", (path_id,)).fetchone()
        if not prow:
            return None
        result = {
            "id": prow["id"], "goal_id": prow["goal_id"],
            "title": prow["title"], "status": prow["status"], "stages": [],
        }
        srows = conn.execute(
            "SELECT * FROM stages WHERE path_id=? ORDER BY position, id", (path_id,)
        ).fetchall()
        for srow in srows:
            stage = {
                "id": srow["id"], "path_id": srow["path_id"],
                "title": srow["title"], "position": srow["position"], "tasks": [],
            }
            trows = conn.execute(
                "SELECT * FROM tasks WHERE stage_id=? ORDER BY id", (srow["id"],)
            ).fetchall()
            stage["tasks"] = [_task_to_dict(t) for t in trows]
            result["stages"].append(stage)
        return result


def get_task(task_id: int, path: Path | None = None) -> dict | None:
    with _conn(path) as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    return _task_to_dict(row) if row else None


def get_stage_tasks(stage_id: int, path: Path | None = None) -> list[dict]:
    with _conn(path) as conn:
        rows = conn.execute("SELECT * FROM tasks WHERE stage_id=? ORDER BY id", (stage_id,)).fetchall()
    return [_task_to_dict(r) for r in rows]


# ---------- attempts ----------

def record_attempt(task_id: int, difficulty: int, result: str, evidence: str = "",
                   path: Path | None = None) -> int:
    _require_difficulty(difficulty)
    if result not in ("pass", "fail"):
        raise ValueError("result 必须是 pass 或 fail")
    ts = datetime.now(timezone.utc).isoformat()
    with _conn(path) as conn:
        cur = conn.execute(
            "INSERT INTO attempts(task_id, ts, difficulty, result, evidence) VALUES(?,?,?,?,?)",
            (task_id, ts, difficulty, result, evidence),
        )
        return cur.lastrowid


def get_attempts(task_id: int, path: Path | None = None) -> list[dict]:
    with _conn(path) as conn:
        rows = conn.execute("SELECT * FROM attempts WHERE task_id=? ORDER BY id", (task_id,)).fetchall()
    return [dict(r) for r in rows]
