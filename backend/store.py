"""SQLite 存储层（sqlite3 标准库）：CRUD，全参数化。

G3 第 2 步：schema 建表 + 索引 + 外键级联 + CRUD。
G3 第 7 步 A：flow-v2 增量——placement_tests/conversations 新表；
stages + status/objective/summary；attempts + submission/file_name/file_path/llm_review/forced。
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
    position INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','review','learning','done')),
    objective TEXT NOT NULL DEFAULT '',
    summary TEXT
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
    evidence TEXT NOT NULL DEFAULT '',
    submission TEXT NOT NULL DEFAULT '',
    file_name TEXT,
    file_path TEXT,
    llm_review TEXT NOT NULL DEFAULT '',
    forced INTEGER NOT NULL DEFAULT 0 CHECK (forced IN (0,1))
);
CREATE TABLE IF NOT EXISTS placement_tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    questions TEXT NOT NULL,
    answers TEXT,
    created_at TEXT NOT NULL,
    graded_at TEXT
);
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user','assistant')),
    content TEXT NOT NULL,
    ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lesson_plan_examples (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    activities TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_paths_goal ON paths(goal_id);
CREATE INDEX IF NOT EXISTS idx_stages_path ON stages(path_id);
CREATE INDEX IF NOT EXISTS idx_tasks_stage ON tasks(stage_id);
CREATE INDEX IF NOT EXISTS idx_attempts_task ON attempts(task_id);
CREATE INDEX IF NOT EXISTS idx_placement_goal ON placement_tests(goal_id);
CREATE INDEX IF NOT EXISTS idx_conv_task ON conversations(task_id);
"""


_EXAMPLE_ACTIVITY_FIELDS = (
    "id",
    "position",
    "title",
    "student_task",
    "answer_space",
    "feedback_record",
    "teacher_observation",
    "teacher_prompt",
    "answer_check",
    "stuck_support",
)

_DEFAULT_LESSON_PLAN_EXAMPLE = {
    "id": "default",
    "label": "示例",
    "title": "集合与函数备课稿",
    "activities": [
        {
            "id": "set-inequality-check",
            "position": 0,
            "title": "集合与不等式检查",
            "student_task": "判断给出的元素是否属于集合，并写出每一步判断理由。",
            "answer_space": "判断：____________________\n理由：____________________",
            "feedback_record": "我在哪一步不确定：____________________",
            "teacher_observation": "先看学生是否主动区分元素、集合与不等式条件。",
            "teacher_prompt": "你用了哪个条件？把它代回去会发生什么？",
            "answer_check": "核查集合符号、条件范围和不等式方向是否一致。",
            "stuck_support": "让学生先圈出条件中的变量和范围，再口头说出判断依据。",
        },
        {
            "id": "function-relation-judgement",
            "position": 1,
            "title": "函数关系判断",
            "student_task": "判断每个关系是不是函数，并写出理由。",
            "answer_space": "判断：____________________\n理由：____________________",
            "feedback_record": "我检查了输入和输出：____________________",
            "teacher_observation": "观察学生是否说出“每个输入恰好一个输出”，而非只凭图形印象。",
            "teacher_prompt": "同一个输入可以对应几个输出？逐个输入检查。",
            "answer_check": "函数要求定义域内每个输入恰好对应一个输出。",
            "stuck_support": "把关系写成输入与输出的配对，先检查有没有一个输入连到两个输出。",
        },
        {
            "id": "function-domain-practice",
            "position": 2,
            "title": "函数定义域练习",
            "student_task": "如果前一项完成顺利，从情境中写出函数自变量的取值范围。",
            "answer_space": "自变量表示：____________________\n取值范围：____________________",
            "feedback_record": "情境限制是：____________________",
            "teacher_observation": "仅在函数判断已稳固时进入，检查学生是否从情境限制而非公式习惯确定范围。",
            "teacher_prompt": "这个量在情境里能取负数吗？还需要满足什么条件？",
            "answer_check": "定义域由情境和表达式共同限制，不能只看一种限制。",
            "stuck_support": "先用一句话说明自变量代表什么，再列出不能出现的取值。",
        },
    ],
}


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


def _validate_example_activities(activities) -> list[dict]:
    if not isinstance(activities, list) or not activities:
        raise ValueError("activities 必须是非空列表")
    validated = []
    for position, activity in enumerate(activities):
        if not isinstance(activity, dict):
            raise ValueError("每个 activity 必须是对象")
        output = {}
        for field in _EXAMPLE_ACTIVITY_FIELDS:
            value = activity.get(field)
            if field == "position":
                if isinstance(value, bool) or not isinstance(value, int) or value != position:
                    raise ValueError("activity.position 必须从 0 开始连续编号")
            elif not isinstance(value, str) or not value.strip():
                raise ValueError(f"activity.{field} 必须是非空字符串")
            output[field] = value
        validated.append(output)
    return validated


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


# ---------- lesson plan examples ----------

def _lesson_plan_example_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "label": "示例",
        "title": row["title"],
        "activities": json.loads(row["activities"]),
        "updated_at": row["updated_at"],
    }


def get_lesson_plan_example(example_id: str, path: Path | None = None) -> dict | None:
    with _conn(path) as conn:
        row = conn.execute(
            "SELECT * FROM lesson_plan_examples WHERE id=?", (example_id,)
        ).fetchone()
    return _lesson_plan_example_to_dict(row) if row else None


def get_or_create_default_lesson_plan_example(path: Path | None = None) -> dict:
    """首次浏览时创建内置示例，不写入 goals、paths 或任何学生数据。"""
    with _conn(path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO lesson_plan_examples(id, title, activities, updated_at) "
            "VALUES(?,?,?,?)",
            (
                _DEFAULT_LESSON_PLAN_EXAMPLE["id"],
                _DEFAULT_LESSON_PLAN_EXAMPLE["title"],
                json.dumps(_DEFAULT_LESSON_PLAN_EXAMPLE["activities"], ensure_ascii=False),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        row = conn.execute(
            "SELECT * FROM lesson_plan_examples WHERE id=?",
            (_DEFAULT_LESSON_PLAN_EXAMPLE["id"],),
        ).fetchone()
    return _lesson_plan_example_to_dict(row)


def update_lesson_plan_example(example_id: str, title: str, activities: list,
                               path: Path | None = None) -> dict | None:
    _require_nonempty_str(example_id, "example_id")
    _require_nonempty_str(title, "title")
    activities = _validate_example_activities(activities)
    with _conn(path) as conn:
        cur = conn.execute(
            "UPDATE lesson_plan_examples SET title=?, activities=?, updated_at=? WHERE id=?",
            (title, json.dumps(activities, ensure_ascii=False),
             datetime.now(timezone.utc).isoformat(), example_id),
        )
        if cur.rowcount == 0:
            return None
        row = conn.execute(
            "SELECT * FROM lesson_plan_examples WHERE id=?", (example_id,)
        ).fetchone()
    return _lesson_plan_example_to_dict(row)


def list_lesson_plan_examples(path: Path | None = None) -> list[dict]:
    with _conn(path) as conn:
        rows = conn.execute("SELECT * FROM lesson_plan_examples ORDER BY id").fetchall()
    return [_lesson_plan_example_to_dict(row) for row in rows]


def lesson_plan_student_task_page(example: dict) -> dict:
    """学生页只投影活动的学生可见字段，永不带教师核查内容。"""
    return {
        "id": example["id"],
        "label": example["label"],
        "title": example["title"],
        "activities": [
            {field: activity[field] for field in (
                "id", "position", "title", "student_task", "answer_space", "feedback_record"
            )}
            for activity in example["activities"]
        ],
        "updated_at": example["updated_at"],
    }


# ---------- paths / stages / tasks ----------

_STAGE_STATUSES = ("pending", "review", "learning", "done")


def _require_stage_status(status: str) -> str:
    if status not in _STAGE_STATUSES:
        raise ValueError("stage status 必须是 pending/review/learning/done")
    return status


def _insert_stage(conn: sqlite3.Connection, path_id: int, title: str, position: int | None,
                  objective: str = "", status: str = "pending") -> int:
    _require_nonempty_str(title, "title")
    _require_stage_status(status)
    if not isinstance(objective, str):
        raise ValueError("objective 必须是 str")
    if position is None:
        row = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS n FROM stages WHERE path_id=?", (path_id,)
        ).fetchone()
        position = row["n"]
    cur = conn.execute(
        "INSERT INTO stages(path_id, title, position, status, objective) VALUES(?,?,?,?,?)",
        (path_id, title, position, status, objective),
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
            sid = _insert_stage(conn, pid, st.get("title", ""), None,
                                st.get("objective", ""), st.get("status", "pending"))
            for t in st.get("tasks", []):
                _insert_task(conn, sid, **t)
        return pid


def update_path(path_id: int, title: str, stages: list[dict], path: Path | None = None) -> None:
    """候选修改落地：title+stages 全量替换——单事务内删旧 stages（外键级联清 tasks/attempts）
    → 重插；中途失败原子回滚（旧树无恙）。不查 status（draft 门 → API 层 409）、不改 status。"""
    _require_nonempty_str(title, "title")
    if not isinstance(stages, list):
        raise ValueError("stages 必须是 list")
    with _conn(path) as conn:
        row = conn.execute("SELECT id FROM paths WHERE id=?", (path_id,)).fetchone()
        if row is None:
            raise ValueError(f"path {path_id} 不存在")
        conn.execute("UPDATE paths SET title=? WHERE id=?", (title, path_id))
        conn.execute("DELETE FROM stages WHERE path_id=?", (path_id,))
        for st in stages:
            if not isinstance(st, dict):
                raise ValueError("每个 stage 必须是 dict")
            sid = _insert_stage(conn, path_id, st.get("title", ""), None,
                                st.get("objective", ""), st.get("status", "pending"))
            for t in st.get("tasks", []):
                _insert_task(conn, sid, **t)


def create_stage(path_id: int, title: str, position: int | None = None,
                 objective: str = "", path: Path | None = None) -> int:
    with _conn(path) as conn:
        return _insert_stage(conn, path_id, title, position, objective)


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


def set_stage_status(stage_id: int, status: str, path: Path | None = None) -> None:
    """阶段状态机推进：pending→review→learning→done（合法跳转序由 API 层把关，store 只查值域）。"""
    _require_stage_status(status)
    with _conn(path) as conn:
        cur = conn.execute("UPDATE stages SET status=? WHERE id=?", (status, stage_id))
        if cur.rowcount == 0:
            raise ValueError(f"stage {stage_id} 不存在")


def set_stage_summary(stage_id: int, summary: str, path: Path | None = None) -> None:
    """阶段沉淀写入/刷新（NULL=未沉淀；LLM 失败时调用方传占位文案，非空）。"""
    _require_nonempty_str(summary, "summary")
    with _conn(path) as conn:
        cur = conn.execute("UPDATE stages SET summary=? WHERE id=?", (summary, stage_id))
        if cur.rowcount == 0:
            raise ValueError(f"stage {stage_id} 不存在")


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
                "title": srow["title"], "position": srow["position"],
                "status": srow["status"], "objective": srow["objective"],
                "summary": srow["summary"], "tasks": [],
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


def list_paths(goal_id: int | None = None, path: Path | None = None) -> list[dict]:
    """列出路径（嵌套完整树，结构与 get_path 一致）；goal_id 给定则只回该 goal 的路径。"""
    with _conn(path) as conn:
        if goal_id is None:
            rows = conn.execute("SELECT id FROM paths ORDER BY id").fetchall()
        else:
            rows = conn.execute(
                "SELECT id FROM paths WHERE goal_id=? ORDER BY id", (goal_id,)
            ).fetchall()
    return [get_path(r["id"], path) for r in rows]


def get_stage_tasks(stage_id: int, path: Path | None = None) -> list[dict]:
    with _conn(path) as conn:
        rows = conn.execute("SELECT * FROM tasks WHERE stage_id=? ORDER BY id", (stage_id,)).fetchall()
    return [_task_to_dict(r) for r in rows]


# ---------- attempts ----------

def record_attempt(task_id: int, difficulty: int, result: str, evidence: str = "",
                   submission: str = "", file_name: str | None = None,
                   file_path: str | None = None, llm_review: str = "",
                   forced: int = 0, path: Path | None = None) -> int:
    """记录一次判定。flow-v2 新列：submission（artifact 文本载体）、file_name/file_path
    （附件元数据，原名仅元数据、落盘 uuid 名）、llm_review（LLM 审核意见）、
    forced（1=用户终裁强行通过 D2）。全部缺省值保持 quiz 旧调用零破坏。"""
    _require_difficulty(difficulty)
    if result not in ("pass", "fail"):
        raise ValueError("result 必须是 pass 或 fail")
    if not isinstance(submission, str):
        raise ValueError("submission 必须是 str")
    for value, name in ((file_name, "file_name"), (file_path, "file_path")):
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{name} 必须是 str 或 None")
    if not isinstance(llm_review, str):
        raise ValueError("llm_review 必须是 str")
    if isinstance(forced, bool) or forced not in (0, 1):
        raise ValueError("forced 必须是 0 或 1")
    ts = datetime.now(timezone.utc).isoformat()
    with _conn(path) as conn:
        cur = conn.execute(
            "INSERT INTO attempts(task_id, ts, difficulty, result, evidence, submission, "
            "file_name, file_path, llm_review, forced) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (task_id, ts, difficulty, result, evidence, submission,
             file_name, file_path, llm_review, forced),
        )
        return cur.lastrowid


def get_attempts(task_id: int, path: Path | None = None) -> list[dict]:
    with _conn(path) as conn:
        rows = conn.execute("SELECT * FROM attempts WHERE task_id=? ORDER BY id", (task_id,)).fetchall()
    return [dict(r) for r in rows]


# ---------- placement_tests（水平测试卷，flow-v2 D1） ----------

def create_placement_test(goal_id: int, questions: list[dict],
                          path: Path | None = None) -> int:
    """落一份校验过的水平测试卷（校验职责在 planner/route，store 只拒明显坏结构）。"""
    if not isinstance(questions, list) or not questions:
        raise ValueError("questions 必须是非空 list")
    if any(not isinstance(q, dict) for q in questions):
        raise ValueError("questions 每个元素必须是 dict")
    created_at = datetime.now(timezone.utc).isoformat()
    with _conn(path) as conn:
        cur = conn.execute(
            "INSERT INTO placement_tests(goal_id, questions, created_at) VALUES(?,?,?)",
            (goal_id, json.dumps(questions, ensure_ascii=False), created_at),
        )
        return cur.lastrowid


def get_placement_test(test_id: int, path: Path | None = None) -> dict | None:
    with _conn(path) as conn:
        row = conn.execute(
            "SELECT * FROM placement_tests WHERE id=?", (test_id,)
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"], "goal_id": row["goal_id"],
        "questions": json.loads(row["questions"]),
        "answers": json.loads(row["answers"]) if row["answers"] is not None else None,
        "created_at": row["created_at"], "graded_at": row["graded_at"],
    }


def submit_placement_test(test_id: int, answers: list[int], path: Path | None = None) -> None:
    """整卷提交：answers 为逐题选项索引（int）；已提交的卷不可重交。"""
    if not isinstance(answers, list) or not answers:
        raise ValueError("answers 必须是非空 list")
    if any(isinstance(a, bool) or not isinstance(a, int) for a in answers):
        raise ValueError("answers 每个元素必须是 int")
    with _conn(path) as conn:
        row = conn.execute(
            "SELECT id, graded_at FROM placement_tests WHERE id=?", (test_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"placement_test {test_id} 不存在")
        if row["graded_at"] is not None:
            raise ValueError(f"placement_test {test_id} 已提交，不可重交")
        graded_at = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE placement_tests SET answers=?, graded_at=? WHERE id=?",
            (json.dumps(answers), graded_at, test_id),
        )


# ---------- conversations（chat 按 task 持久化，flow-v2 D5） ----------

def add_message(task_id: int, role: str, content: str, path: Path | None = None) -> int:
    """追加一条 chat 消息；role 仅 user/assistant（D5：只指导不改计划）。"""
    if role not in ("user", "assistant"):
        raise ValueError("role 必须是 user 或 assistant")
    _require_nonempty_str(content, "content")
    ts = datetime.now(timezone.utc).isoformat()
    with _conn(path) as conn:
        cur = conn.execute(
            "INSERT INTO conversations(task_id, role, content, ts) VALUES(?,?,?,?)",
            (task_id, role, content, ts),
        )
        return cur.lastrowid


def list_messages(task_id: int, path: Path | None = None) -> list[dict]:
    with _conn(path) as conn:
        rows = conn.execute(
            "SELECT * FROM conversations WHERE task_id=? ORDER BY id", (task_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def export_all(path: Path | None = None) -> dict:
    """全量嵌套导出，并与通用学习路径分开保留示例备课数据。"""
    goals = []
    for goal in list_goals(path):
        entry = dict(goal)
        entry["paths"] = []
        for p in list_paths(goal["id"], path):
            for st in p["stages"]:
                for t in st["tasks"]:
                    t["attempts"] = get_attempts(t["id"], path)
            entry["paths"].append(p)
        goals.append(entry)
    return {"goals": goals, "lesson_plan_examples": list_lesson_plan_examples(path)}
