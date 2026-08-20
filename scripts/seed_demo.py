"""dev-only 造数：绕过 LLM generate（无需 key），直接经 store 建 demo goal/path/attempts。

用法（Custom/ 根目录执行）：python scripts/seed_demo.py
生成后打开 http://127.0.0.1:8000 → 直达执行视图（G3-6 K2 走查）。
说明：每次运行新增一条 demo 路径；仅用于联调；真实数据请走前端正常流程（第 7 步 dogfooding）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import store  # noqa: E402

STAGES = [
    {"title": "阶段一：提示工程基础", "tasks": [
        {"kind": "quiz", "title": "什么是 Prompt", "brief": "理解提示工程的基本概念与作用。",
         "difficulty": 1, "skills": ["提示工程"],
         "quiz": {"q": "以下哪项最能描述 Prompt？",
                  "options": ["给模型的输入指令", "模型的权重参数", "训练数据集"],
                  "answer": 0, "explanation": "Prompt 是给模型的输入指令，用于引导模型产出。"}},
        {"kind": "artifact", "title": "写一份常用提示词清单",
         "brief": "整理一份你在工作/学习中可复用的提示词清单。",
         "difficulty": 1, "skills": ["提示工程"],
         "acceptance": ["至少 5 条提示词", "每条含使用场景"]},
    ]},
    {"title": "阶段二：RAG 核心概念", "tasks": [
        {"kind": "quiz", "title": "RAG 中检索的作用", "brief": "理解检索增强生成为什么需要外部知识库。",
         "difficulty": 2, "skills": ["RAG"],
         "quiz": {"q": "检索增强生成（RAG）主要解决什么问题？",
                  "options": ["模型参数规模不足", "知识时效性/领域知识不足", "训练速度过慢"],
                  "answer": 1, "explanation": "RAG 通过外部检索弥补模型知识时效性与领域知识的不足。"}},
        {"kind": "artifact", "title": "画出 RAG 流水线图",
         "brief": "用一张图梳理 RAG 的完整链路：切块 → 嵌入 → 检索 → 生成。",
         "difficulty": 2, "skills": ["RAG", "向量检索"],
         "acceptance": ["包含切块/嵌入/检索/生成四步", "标注每步的作用"]},
    ]},
]


def main() -> None:
    store.init_db()
    gid = store.create_goal("从零学会 AI 工程基础，先掌握提示工程与 RAG",
                            ["提示工程", "RAG", "向量检索"])
    pid = store.create_path(gid, "AI 工程入门路径（demo）", stages=STAGES)
    store.set_path_status(pid, "active")
    path = store.get_path(pid)
    first = path["stages"][0]["tasks"][0]
    store.record_attempt(first["id"], first["difficulty"], "pass", "demo seed：答对")
    n_tasks = sum(len(s["tasks"]) for s in path["stages"])
    print(f"done: goal#{gid} path#{pid}（active，{len(path['stages'])} 阶段 / {n_tasks} 任务，"
          f"首任务已 pass，进度 {round(100 / n_tasks)}%）")
    print("打开 http://127.0.0.1:8000 → 执行视图（K2 走查）")


if __name__ == "__main__":
    main()
