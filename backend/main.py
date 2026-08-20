"""FastAPI 入口：路由 goals/paths/tasks/attempts/export。

G2 脚手架阶段：仅提供 /health 健康检查，保证骨架可启动；
其余路由在分步实施第 5 步串通；启动时调用 store.init_db()。
"""
from fastapi import FastAPI

app = FastAPI(title="Custom", version="0.1.0")


@app.get("/health")
def health() -> dict:
    """健康检查：骨架可启动的最小验证点。"""
    return {"status": "ok"}


# TODO(G3-第2步): 启动时 store.init_db()
# TODO(G3-第5步): 挂载路由 goals/paths/tasks/attempts/export


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000)
