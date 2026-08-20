"""G3-4 审核证据：假 client 走完整闭环（generate → validate → 格式化打印），一次性演示脚本。"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import planner

RAW = {
    "title": "从零上手 AI Agent 开发",
    "notes": "LLM 附加说明（校验时应被丢弃）",
    "stages": [
        {"title": "阶段一：Agent 概念与 LLM 调用", "tasks": [
            {"kind": "quiz", "title": "什么是 Agent", "brief": "理解 Agent 的感知-决策-行动循环",
             "difficulty": 1, "skills": ["LLM 基础", "Agent 概念"],
             "quiz": {"q": "以下哪项最能描述 LLM Agent 的核心循环？",
                      "options": ["感知→规划→行动→反馈", "只做文本续写", "仅做数据库查询"], "answer": 0,
                      "explanation": "Agent 循环 = 感知环境、规划、调用工具行动、根据反馈迭代。", "hint": "多余字段"},
             "meta": "多余"},
            {"kind": "artifact", "title": "跑通第一个 API 调用", "brief": "用 openai SDK 调 DeepSeek 并打印回复",
             "difficulty": 2, "skills": ["API 调用"],
             "acceptance": ["代码可运行", "输出贴到学习记录"]},
        ]},
        {"title": "阶段二：工具调用与 MCP", "tasks": [
            {"kind": "quiz", "title": "函数调用原理", "brief": "理解 function calling 与 MCP 的关系",
             "difficulty": 2, "skills": ["MCP"],
             "quiz": {"q": "MCP 解决的核心问题是什么？",
                      "options": ["统一 Agent 与外部工具的连接协议", "压缩模型体积", "加速网络"], "answer": 0,
                      "explanation": "MCP = Model Context Protocol，统一工具/数据源接入。"}},
            {"kind": "artifact", "title": "接一个 MCP 工具", "brief": "把天气查询工具接入自己的 Agent",
             "difficulty": 3, "skills": ["MCP", "Agent"],
             "acceptance": ["工具调用成功", "失败路径有兜底输出"]},
        ]},
        {"title": "阶段三：评测与交付", "tasks": [
            {"kind": "quiz", "title": "为什么需要评测集", "brief": "理解 Agent 评测的基本方法",
             "difficulty": 1, "skills": ["评测"],
             "quiz": {"q": "Agent 评测最难的部分通常是？",
                      "options": ["定义可复现的判定标准", "写代码", "选模型"], "answer": 0,
                      "explanation": "Agent 输出开放性高，判定标准最难定义。"}},
        ]},
    ],
}


def _fake_client():
    def create(**kwargs):
        content = "```json\n" + json.dumps(RAW, ensure_ascii=False) + "\n```"
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


raw = planner.generate_candidate_path("从零上手 AI Agent 开发", ["LLM", "Agent", "MCP"], _fake_client())
validated = planner.validate_candidate_path(raw)
print("=== 候选路径（已通过严格校验，待用户确认后落库） ===")
print(json.dumps(validated, ensure_ascii=False, indent=2))
tasks = [t for s in validated["stages"] for t in s["tasks"]]
print("=== 统计：stages", len(validated["stages"]), "| tasks", len(tasks),
      "| 难度分布", sorted(t["difficulty"] for t in tasks), "===")
