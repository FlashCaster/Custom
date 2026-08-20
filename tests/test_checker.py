"""G3-第3步 test_checker.py：checker 三函数 TDD（quiz 判分 + 难度推荐 + 验收清单确认）。

2.4 标准用例表（正常 ≥3 组 + 攻击 ≥10 组，八大类每类 ≥1，组合 ≥2）：

| 编号 | 类别 | 输入 | 预期行为 |
|---|---|---|---|
| T01 | 正常-最小 | judge 索引答对（answer=0） | pass + explanation |
| T02 | 正常-典型 | judge 文本答对（"rag" vs "RAG"） | pass（大小写不敏感） |
| T03 | 正常-复杂 | recommend 连续 2 pass 升级；confirm 全勾/部分勾 | 升 1 级 / True / False |
| A01 | 攻击-空数据 | judge 空白 answer / recommend 空历史 / confirm 空 acceptance | fail / 1 / ValueError |
| A02 | 攻击-极值 | recommend fail@0 / 2pass@3 | 0（N0 下限）/ 3（N3 上限） |
| A03 | 攻击-越界(用户) | judge 索引 99 / 数字串 "99" | fail |
| A04 | 攻击-越界(数据) | quiz.answer=5（仅 3 选项） | ValueError |
| A05 | 攻击-空选项 | options=[] | ValueError |
| A06 | 攻击-脏数据 | 文本答案 "  Rag " 前后空格 | pass（去空格） |
| A07 | 攻击-特殊字符 | 选项含引号/emoji，文本匹配 | pass |
| A08 | 攻击-异常格式 | 数字串 "0" 当索引 / result="maybe" | 按索引判 / ValueError |
| A09 | 攻击-缺失字段 | task 缺 quiz / history 项缺 difficulty | ValueError |
| A10 | 组合1 | quiz.answer 越界 + options 空 | ValueError |
| A11 | 组合2 | 长 history 混合 fail+pass，只取最近两条 | 按最近两条判 |
| A12 | 攻击-类型 | bool/list/dict 当 answer / checklist 含非 bool / history 非 dict | fail / ValueError |
"""
from __future__ import annotations

import pytest

from backend import checker


def _quiz(**over) -> dict:
    base = {
        "q": "RAG 是什么？",
        "options": ["RAG", "随机森林", "梯度下降"],
        "answer": 0,
        "explanation": "RAG = Retrieval-Augmented Generation",
    }
    base.update(over)
    return base


def _task(**over) -> dict:
    base = {
        "kind": "quiz",
        "title": "RAG 基础",
        "difficulty": 1,
        "brief": "b",
        "quiz": _quiz(),
    }
    base.update(over)
    return base


# ---------- 正常 ----------


def test_t01_judge_index_answer_pass():
    out = checker.judge_quiz(_task(), 0)
    assert out == {"result": "pass", "explanation": "RAG = Retrieval-Augmented Generation"}


def test_t02_judge_text_answer_case_insensitive():
    assert checker.judge_quiz(_task(), "rag")["result"] == "pass"


def test_t03_recommend_upgrade_and_confirm():
    history = [
        {"difficulty": 1, "result": "pass"},
        {"difficulty": 1, "result": "pass"},
    ]
    assert checker.recommend_difficulty(history) == 2
    task = _task(acceptance=["产出报告", "截图"])
    assert checker.confirm_acceptance(task, [True, True]) is True
    assert checker.confirm_acceptance(task, [True, False]) is False


# ---------- 攻击 ----------


def test_a01_empty_inputs():
    task = _task()
    assert checker.judge_quiz(task, None)["result"] == "fail"
    assert checker.judge_quiz(task, "")["result"] == "fail"
    assert checker.judge_quiz(task, "   ")["result"] == "fail"
    assert checker.recommend_difficulty([]) == 1
    with pytest.raises(ValueError):
        checker.confirm_acceptance(_task(acceptance=[]), [])


def test_a02_difficulty_limits():
    assert checker.recommend_difficulty([{"difficulty": 0, "result": "fail"}]) == 0
    up = [{"difficulty": 3, "result": "pass"}, {"difficulty": 3, "result": "pass"}]
    assert checker.recommend_difficulty(up) == 3


def test_a03_user_answer_out_of_range():
    task = _task()
    out = checker.judge_quiz(task, 99)
    assert out == {"result": "fail", "explanation": "RAG = Retrieval-Augmented Generation"}
    assert checker.judge_quiz(task, "99")["result"] == "fail"


def test_a04_quiz_answer_out_of_range():
    with pytest.raises(ValueError):
        checker.judge_quiz(_task(quiz=_quiz(answer=5)), 0)


def test_a05_empty_options():
    with pytest.raises(ValueError):
        checker.judge_quiz(_task(quiz=_quiz(options=[])), 0)


def test_a06_text_answer_stripped():
    assert checker.judge_quiz(_task(), "  Rag ")["result"] == "pass"


def test_a07_special_chars_in_option():
    task = _task(quiz=_quiz(options=['He said "Hi" 🎉', "其他"]))
    assert checker.judge_quiz(task, 'he said "hi" 🎉')["result"] == "pass"


def test_a08_numeric_string_and_bad_result():
    assert checker.judge_quiz(_task(), "0")["result"] == "pass"  # 纯数字串当索引
    with pytest.raises(ValueError):
        checker.recommend_difficulty([{"difficulty": 1, "result": "maybe"}])


def test_a09_missing_fields():
    with pytest.raises(ValueError):
        checker.judge_quiz({"kind": "quiz"}, 0)  # 缺 quiz
    with pytest.raises(ValueError):
        checker.recommend_difficulty([{"result": "pass"}])  # 缺 difficulty


def test_a10_combo_out_of_range_and_empty_options():
    with pytest.raises(ValueError):
        checker.judge_quiz(_task(quiz=_quiz(answer=9, options=[])), 9)


def test_a11_long_history_only_last_two_matter():
    history = [
        {"difficulty": 2, "result": "fail"},
        {"difficulty": 2, "result": "pass"},
        {"difficulty": 3, "result": "fail"},
        {"difficulty": 1, "result": "pass"},
        {"difficulty": 1, "result": "pass"},
    ]
    assert checker.recommend_difficulty(history) == 2


def test_a12_wrong_types():
    task = _task()
    for bad in (True, False, ["RAG"], {"a": 1}):
        assert checker.judge_quiz(task, bad)["result"] == "fail"
    with pytest.raises(ValueError):
        checker.confirm_acceptance(_task(acceptance=["a", "b"]), [True, 1])
    with pytest.raises(ValueError):
        checker.recommend_difficulty([None])
