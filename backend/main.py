"""FastAPI 入口：路由 goals/paths/tasks/attempts/export + 前端静态伺服。

G3 第 5 步：8 路由串通 store/planner/checker；统一错误映射（422/404/400/502/503/500）；
lifespan 启动时 store.init_db(store.DB_PATH)（补 G2 TODO，DB 位置可测试 monkeypatch）；
get_llm_client 工厂：DEEPSEEK_API_KEY 环境变量（无 key → 503），懒 import openai（无 key 不崩）。
G3 第 6 步：PUT /paths/{id}（候选修改全量替换，仅 draft，409 状态门）+ POST /paths/{id}/complete
（幂等置 done）+ StaticFiles mount "/"（html=True，GET / → index.html；目录取 __file__ 相对，免 CWD 依赖）。
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend import checker, planner, store


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.init_db(store.DB_PATH)
    yield


app = FastAPI(title="Custom", version="0.1.0", lifespan=lifespan)


# ---------- 错误映射（API 层统一约定，G3-5 计划 §2.1） ----------

@app.exception_handler(ValueError)
async def _value_error_handler(request, exc: ValueError) -> JSONResponse:
    """checker/planner/store 防御性 ValueError → 400，detail 原样带原因。"""
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(sqlite3.IntegrityError)
async def _integrity_error_handler(request, exc: sqlite3.IntegrityError) -> JSONResponse:
    """外键/约束兜底（正常路径 404 已拦截）→ 500。"""
    return JSONResponse(status_code=500, content={"detail": "数据库完整性错误"})


@app.get("/health")
def health() -> dict:
    """健康检查：骨架可启动的最小验证点。"""
    return {"status": "ok"}


# ---------- 请求模型（strict：拒绝 int→str/bool→int 之类静默强转） ----------

class GoalCreate(BaseModel):
    model_config = ConfigDict(strict=True)

    statement: str = Field(max_length=500)
    interests: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("statement")
    @classmethod
    def _statement_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("statement 不能为空白")
        return v

    @field_validator("interests")
    @classmethod
    def _interest_item_length(cls, v: list[str]) -> list[str]:
        if any(len(i) > 100 for i in v):
            raise ValueError("interests 单项超长（>100）")
        return v


class AttemptCreate(BaseModel):
    model_config = ConfigDict(strict=True)

    answer: int | str | None = None
    checklist: list[bool] | None = None


class PathUpdate(BaseModel):
    """PUT 全量替换入参：深度校验全部交给 planner.validate（400），此处只守顶层类型（422）。"""
    model_config = ConfigDict(strict=True)

    title: str
    stages: list


# ---------- LLM client 工厂 ----------

def get_llm_client():
    """读 DEEPSEEK_API_KEY → OpenAI 兼容 client（base_url 指向 DeepSeek）。

    无 key → 503（路由级语义）；openai 懒 import，未装/无 key 不影响其余路由。
    """
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise HTTPException(status_code=503, detail="未配置 DEEPSEEK_API_KEY")
    from openai import OpenAI

    return OpenAI(api_key=key, base_url="https://api.deepseek.com")


# ---------- goals ----------

@app.post("/goals", status_code=201)
def create_goal_route(body: GoalCreate) -> dict:
    """建目标 → 201 + get_goal 完整 dict。"""
    gid = store.create_goal(body.statement, body.interests)
    return store.get_goal(gid)


@app.get("/goals")
def list_goals_route() -> list[dict]:
    return store.list_goals()


# ---------- paths ----------

@app.post("/goals/{goal_id}/paths/generate", status_code=201)
def generate_path_route(goal_id: int, client=Depends(get_llm_client)) -> dict:
    """LLM 生成候选：generate → validate → create_path(draft) → 201 + get_path 完整树。

    本步只产 draft，不自动 active（用户确认落地的开关是 activate）。
    """
    goal = store.get_goal(goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail=f"goal {goal_id} 不存在")
    try:
        raw = planner.generate_candidate_path(goal["statement"], goal["interests"], client)
    except ValueError:
        raise  # 解析失败 → 400 兜底
    except Exception as exc:  # noqa: BLE001 网络/API 错 → 502
        raise HTTPException(status_code=502, detail=f"LLM 调用失败: {exc}") from exc
    candidate = planner.validate_candidate_path(raw)
    pid = store.create_path(goal_id, candidate["title"], candidate["stages"])
    return store.get_path(pid)


@app.post("/paths/{path_id}/activate")
def activate_path_route(path_id: int) -> dict:
    """用户确认候选落地：置 active（幂等，重复调用 200）。"""
    if store.get_path(path_id) is None:
        raise HTTPException(status_code=404, detail=f"path {path_id} 不存在")
    store.set_path_status(path_id, "active")
    return store.get_path(path_id)


@app.put("/paths/{path_id}")
def update_path_route(path_id: int, body: PathUpdate) -> dict:
    """候选修改落地：body {title, stages} 全量替换。仅 draft 可改（active/done → 409）；
    复用 planner.validate_candidate_path 全部校验（坏结构 → 400）；store.update_path 原子事务。"""
    path = store.get_path(path_id)
    if path is None:
        raise HTTPException(status_code=404, detail=f"path {path_id} 不存在")
    if path["status"] != "draft":
        raise HTTPException(status_code=409,
                            detail=f"path {path_id} 状态为 {path['status']}，仅 draft 可修改")
    candidate = planner.validate_candidate_path({"title": body.title, "stages": body.stages})
    store.update_path(path_id, candidate["title"], candidate["stages"])
    return store.get_path(path_id)


@app.post("/paths/{path_id}/complete")
def complete_path_route(path_id: int) -> dict:
    """全部完成置 done（幂等，任意状态可直接 complete，重复调用 200）。"""
    if store.get_path(path_id) is None:
        raise HTTPException(status_code=404, detail=f"path {path_id} 不存在")
    store.set_path_status(path_id, "done")
    return store.get_path(path_id)


@app.get("/paths/{path_id}")
def get_path_route(path_id: int) -> dict:
    path = store.get_path(path_id)
    if path is None:
        raise HTTPException(status_code=404, detail=f"path {path_id} 不存在")
    return path


@app.get("/paths/{path_id}/progress")
def path_progress_route(path_id: int) -> dict:
    """进度派生（只读，不改 path status）：任务 done ⇔ 存在任意 pass attempt。"""
    path = store.get_path(path_id)
    if path is None:
        raise HTTPException(status_code=404, detail=f"path {path_id} 不存在")
    tasks = [t for s in path["stages"] for t in s["tasks"]]
    completed = 0
    current_task_id = current_stage_id = None
    for t in tasks:
        if any(a["result"] == "pass" for a in store.get_attempts(t["id"])):
            completed += 1
        elif current_task_id is None:
            current_task_id, current_stage_id = t["id"], t["stage_id"]
    total = len(tasks)
    percent = 100 if total == 0 else round(completed * 100 / total)
    return {"current_task_id": current_task_id, "current_stage_id": current_stage_id,
            "completed": completed, "total": total, "percent": int(percent)}


# ---------- attempts ----------

@app.post("/tasks/{task_id}/attempts")
def attempt_route(task_id: int, body: AttemptCreate) -> dict:
    """完成判定双模：quiz {answer} / artifact {checklist} → 判分 → record_attempt（pass/fail 都入库）。

    返回 {result, evidence, recommended_difficulty}；difficulty 快照 = task.difficulty（ADR 判分契约）。
    """
    task = store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"task {task_id} 不存在")
    if task["kind"] == "quiz":
        verdict = checker.judge_quiz(task, body.answer)
        result, evidence = verdict["result"], verdict["explanation"]
    else:
        ok = checker.confirm_acceptance(task, body.checklist)
        result, evidence = ("pass", "全部勾选") if ok else ("fail", "未全部勾选")
    store.record_attempt(task_id, task["difficulty"], result, evidence)
    recommended = checker.recommend_difficulty(store.get_attempts(task_id))
    return {"result": result, "evidence": evidence, "recommended_difficulty": recommended}


# ---------- export ----------

@app.get("/export")
def export_route() -> dict:
    """全量嵌套导出：goals→paths→stages→tasks→attempts（数据归用户）。"""
    return store.export_all()


# ---------- 静态伺服（G3-6：挂在全部 API 路由之后，先匹配路由后落 mount） ----------

_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000)
