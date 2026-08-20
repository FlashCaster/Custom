"""G3-第4步 test_planner.py：planner 两函数 TDD（DeepSeek 候选生成 + 严格校验，client 全 mock）。

2.4 标准用例表（正常 ≥3 组 + 攻击 ≥10 组，八大类每类 ≥1，组合 ≥2）：

| 编号 | 类别 | 输入 | 预期行为 |
|---|---|---|---|
| T01 | 正常-最小 | validate 单阶段单 quiz 任务（最小字段） | 通过，输出与规范化结构一致 |
| T02 | 正常-典型 | validate 多阶段 quiz+artifact 混合 + 各层未知键 | 通过，未知键被丢弃 |
| T03 | 正常-复杂 | 难度 0/3 极值 + 引号/emoji 文本 | 通过，值原样保留 |
| T04 | 正常-集成 | generate mock 返回合法 JSON（含 ``` 代码块壳） | 剥壳返回 dict；调用参数正确 |
| T05 | 正常-集成-store | validate 输出直接 feed store.create_path | 落库成功，get_path 往返一致 |
| A01 | 攻击-空数据 | goal 空串/空白 / interests 非 list[str] / stages=[] / raw 缺 title | ValueError |
| A02 | 攻击-极值 | difficulty -1/4/True | ValueError |
| A03 | 攻击-越界 | quiz.answer 越界 / options 空 / options 7 个 | ValueError |
| A04 | 攻击-脏数据 | title 前后空格 | 通过（strip 后合法），值原样 |
| A05 | 攻击-特殊字符 | 选项含换行/引号/emoji | 通过 |
| A06 | 攻击-异常格式 | generate 返回非 JSON 文本 / JSON 是 list / content 非 str / raw 非 dict | ValueError |
| A07 | 攻击-缺失字段 | task 缺 difficulty / artifact acceptance 缺失或空 | ValueError |
| A08 | 攻击-未知结构 | 顶层多余键（通过丢键）+ task kind 非法 | 丢键 / ValueError |
| A09 | 组合1 | stages 空 + title 空 | ValueError |
| A10 | 组合2 | 合法任务混 1 个非法任务（原子性） | 整体 ValueError |
| A11 | 攻击-类型 | title 是数字 / stages 是 dict / tasks 是 str | ValueError |
| A12 | 攻击-超长 | title 81 字 / option 201 字 | ValueError |
| A13 | 集成-攻击 | mock client 抛 RuntimeError | 原样上抛（不包装） |
"""
from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend import planner, store

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


def _mock_client(content=None, exc=None, captured=None):
    """构造 OpenAI 兼容协议 mock：client.chat.completions.create(**kw)。"""
    def create(**kwargs):
        if captured is not None:
            captured.update(kwargs)
        if exc is not None:
            raise exc
        message = SimpleNamespace(content=content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def _quiz(**over):
    base = {"q": "RAG 是什么？", "options": ["检索增强生成", "随机森林", "梯度下降"],
            "answer": 0, "explanation": "RAG = Retrieval-Augmented Generation"}
    base.update(over)
    return base


def _task(**over):
    base = {"kind": "quiz", "title": "RAG 基础", "brief": "理解 RAG 概念",
            "difficulty": 1, "quiz": _quiz(), "skills": ["提示工程"]}
    base.update(over)
    return base


def _stage(**over):
    base = {"title": "阶段一：基础", "tasks": [_task()]}
    base.update(over)
    return base


def _raw(**over):
    base = {"title": "学习路径", "stages": [_stage()]}
    base.update(over)
    return base


# ---------- 正常 ----------


def test_t01_minimal_single_stage_quiz():
    raw = {
        "title": "RAG 入门",
        "stages": [{
            "title": "基础",
            "tasks": [{
                "kind": "quiz", "title": "RAG 是什么", "brief": "理解概念",
                "difficulty": 1,
                "quiz": {"q": "RAG 全称？", "options": ["检索增强生成", "随机森林"], "answer": 0},
            }],
        }],
    }
    assert planner.validate_candidate_path(raw) == raw


def test_t02_mixed_kinds_unknown_keys_dropped():
    raw = {
        "title": "AI 工程师路径",
        "note": "顶层未知键",
        "stages": [
            {"title": "阶段1", "tasks": [
                {"kind": "quiz", "title": "quiz1", "brief": "b1", "difficulty": 1,
                 "skills": ["prompt"], "quiz": _quiz(hint="多余键"), "extra": 1},
                {"kind": "artifact", "title": "art1", "brief": "b2", "difficulty": 2,
                 "acceptance": ["产出报告"], "skills": ["写作"], "extra2": "x"},
            ]},
            {"title": "阶段2", "tasks": [
                {"kind": "quiz", "title": "quiz2", "brief": "b3", "difficulty": 0,
                 "quiz": _quiz()},
            ]},
        ],
    }
    out = planner.validate_candidate_path(raw)
    assert "note" not in out
    t1 = out["stages"][0]["tasks"][0]
    assert "extra" not in t1 and "hint" not in t1["quiz"]
    assert "extra2" not in out["stages"][0]["tasks"][1]
    assert [t["kind"] for s in out["stages"] for t in s["tasks"]] \
        == ["quiz", "artifact", "quiz"]


def test_t03_difficulty_extremes_and_special_chars():
    raw = _raw(
        title='路径 "极值" 🎉',
        stages=[
            _stage(title="零", tasks=[_task(difficulty=0, brief='含 "引号" 🎉')]),
            _stage(title="满", tasks=[_task(difficulty=3, quiz=_quiz(q="3 级题 🚀？"))]),
        ],
    )
    out = planner.validate_candidate_path(raw)
    diffs = [t["difficulty"] for s in out["stages"] for t in s["tasks"]]
    assert diffs == [0, 3]
    assert out["title"] == '路径 "极值" 🎉'


def test_t04_generate_strips_fence_and_calls_correctly():
    raw = _raw()
    captured = {}
    content = "```json\n" + json.dumps(raw, ensure_ascii=False) + "\n```"
    client = _mock_client(content=content, captured=captured)
    assert planner.generate_candidate_path("学习 RAG", ["LLM", "检索"], client) == raw
    assert captured["temperature"] == 0.3
    assert captured["max_tokens"] == planner.MAX_TOKENS
    assert captured["model"] == planner.DEFAULT_MODEL
    assert captured["messages"][0]["role"] == "system"
    assert "学习 RAG" in captured["messages"][1]["content"]
    # 无代码块壳的合法 JSON 同样可解析
    client2 = _mock_client(content=json.dumps(raw, ensure_ascii=False))
    assert planner.generate_candidate_path("g", [], client2) == raw


def test_t05_validated_output_feeds_store_create_path(db):
    goal_id = store.create_goal("学习 RAG", path=db)
    out = planner.validate_candidate_path(_raw(stages=[
        _stage(),
        _stage(title="阶段二", tasks=[_task(kind="artifact", quiz=None,
                                             acceptance=["产出报告"], skills=["写作"])]),
    ]))
    pid = store.create_path(goal_id, out["title"], out["stages"], path=db)
    got = store.get_path(pid, path=db)
    assert got["title"] == out["title"]
    assert [s["title"] for s in got["stages"]] == ["阶段一：基础", "阶段二"]
    assert [t["kind"] for s in got["stages"] for t in s["tasks"]] == ["quiz", "artifact"]
    assert got["stages"][1]["tasks"][0]["acceptance"] == ["产出报告"]


# ---------- 攻击 ----------


def test_a01_empty_inputs():
    for bad_goal in ("", "   "):
        with pytest.raises(ValueError):
            planner.generate_candidate_path(bad_goal, [], _mock_client(content="{}"))
    for bad_ints in ("x", [1], None):
        with pytest.raises(ValueError):
            planner.generate_candidate_path("目标", bad_ints, _mock_client(content="{}"))
    assert planner.generate_candidate_path("目标", [], _mock_client(content="{}")) == {}
    with pytest.raises(ValueError):
        planner.validate_candidate_path(_raw(stages=[]))
    with pytest.raises(ValueError):
        planner.validate_candidate_path({"stages": [_stage()]})


def test_a02_difficulty_extremes():
    for bad in (-1, 4, True, 1.5, "1"):
        with pytest.raises(ValueError):
            planner.validate_candidate_path(_raw(stages=[_stage(tasks=[_task(difficulty=bad)])]))


def test_a03_quiz_answer_and_options_out_of_range():
    with pytest.raises(ValueError):
        planner.validate_candidate_path(_raw(stages=[_stage(tasks=[_task(quiz=_quiz(answer=3))])]))
    with pytest.raises(ValueError):
        planner.validate_candidate_path(_raw(stages=[_stage(tasks=[_task(quiz=_quiz(options=[]))])]))
    too_many = _quiz(options=[f"选项{i}" for i in range(7)])
    with pytest.raises(ValueError):
        planner.validate_candidate_path(_raw(stages=[_stage(tasks=[_task(quiz=too_many)])]))


def test_a04_title_with_surrounding_spaces():
    out = planner.validate_candidate_path(_raw(title="  学习路径  "))
    assert out["title"] == "  学习路径  "  # strip 校验通过，值原样保留


def test_a05_options_with_special_chars():
    raw = _raw(stages=[_stage(tasks=[_task(quiz=_quiz(options=["换行\n选项", '他说 "Hi" 🎉', "其他"]))])])
    out = planner.validate_candidate_path(raw)
    assert out["stages"][0]["tasks"][0]["quiz"]["options"][0] == "换行\n选项"


def test_a06_bad_json_shapes():
    with pytest.raises(ValueError):
        planner.generate_candidate_path("g", [], _mock_client(content="这不是 JSON"))
    with pytest.raises(ValueError):
        planner.generate_candidate_path("g", [], _mock_client(content=json.dumps([1, 2])))
    with pytest.raises(ValueError):
        planner.generate_candidate_path("g", [], _mock_client(content=None))
    with pytest.raises(ValueError):
        planner.validate_candidate_path([1, 2])


def test_a07_missing_required_fields():
    with pytest.raises(ValueError):
        planner.validate_candidate_path(_raw(stages=[_stage(tasks=[_task(difficulty=None)])]))
    for acc in (None, []):
        art = _task(kind="artifact", quiz=None, acceptance=acc)
        with pytest.raises(ValueError):
            planner.validate_candidate_path(_raw(stages=[_stage(tasks=[art])]))


def test_a08_unknown_top_key_dropped_and_bad_kind():
    out = planner.validate_candidate_path(_raw(extra_top="丢弃"))
    assert "extra_top" not in out
    with pytest.raises(ValueError):
        planner.validate_candidate_path(_raw(stages=[_stage(tasks=[_task(kind="hack")])]))


def test_a09_combo_empty_stages_and_title():
    with pytest.raises(ValueError):
        planner.validate_candidate_path({"title": "", "stages": []})


def test_a10_atomicity_one_bad_task_rejects_all():
    raw = _raw(stages=[_stage(tasks=[_task(), _task(difficulty=99)])])
    with pytest.raises(ValueError):
        planner.validate_candidate_path(raw)


def test_a11_wrong_types():
    with pytest.raises(ValueError):
        planner.validate_candidate_path(_raw(title=123))
    with pytest.raises(ValueError):
        planner.validate_candidate_path({"title": "x", "stages": {"title": "s"}})
    with pytest.raises(ValueError):
        planner.validate_candidate_path(_raw(stages=[{"title": "s", "tasks": "不是列表"}]))


def test_a12_overlong_fields():
    with pytest.raises(ValueError):
        planner.validate_candidate_path(_raw(title="字" * 81))
    long_opt = _quiz(options=["正常", "长" * 201])
    with pytest.raises(ValueError):
        planner.validate_candidate_path(_raw(stages=[_stage(tasks=[_task(quiz=long_opt)])]))


def test_a13_client_exception_propagates():
    client = _mock_client(exc=RuntimeError("boom"))
    with pytest.raises(RuntimeError, match="boom"):
        planner.generate_candidate_path("目标", [], client)
