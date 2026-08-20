"""完成检查器：quiz 判分 + 难度推荐规则 + 验收清单确认。

G3-第3步实现（TDD）。判分契约（ADR-2026-08-20-checker判分契约）：
- quiz 数据坏（非 dict / 空选项 / answer 越界）→ ValueError（系统缺陷，防御性兜底，本应由 planner 拦截）；
- 用户输入坏（空白 / 越界索引 / 错文本 / 怪类型）→ 返回 fail（正常交互，不崩溃）。
- 双模答案：索引 int（含纯数字串）或 选项文本 str（大小写不敏感 + 去首尾空格）。
"""
from __future__ import annotations


def judge_quiz(task: dict, answer: object) -> dict:
    """quiz 自动判分：返回 {result: "pass"|"fail", explanation}。"""
    if not isinstance(task, dict):
        raise ValueError("task 必须是 dict")
    quiz = task.get("quiz")
    if not isinstance(quiz, dict):
        raise ValueError("quiz 缺失或不是 dict（坏数据）")
    options = quiz.get("options")
    if not isinstance(options, list) or not options:
        raise ValueError("quiz.options 必须是非空 list")
    correct = quiz.get("answer")
    if isinstance(correct, bool) or not isinstance(correct, int) \
            or not 0 <= correct < len(options):
        raise ValueError("quiz.answer 必须是 0 <= answer < len(options) 的 int")

    def verdict(passed: bool) -> dict:
        return {"result": "pass" if passed else "fail",
                "explanation": quiz.get("explanation", "")}

    # 1. None / 空白字符串 → fail
    if answer is None:
        return verdict(False)
    if isinstance(answer, str):
        text = answer.strip()
        if not text:
            return verdict(False)
        # 3. 纯数字串 → 当索引（先于文本匹配）
        try:
            idx = int(text)
        except ValueError:
            idx = None
        if idx is not None:
            return verdict(idx == correct and 0 <= idx < len(options))
        # 4. 其它字符串 → 大小写不敏感 + 去首尾空格匹配正确选项文本
        expected = str(options[correct]).strip().casefold()
        return verdict(text.casefold() == expected)
    # 2. int（非 bool）→ 当索引；越界 → fail
    if isinstance(answer, int) and not isinstance(answer, bool):
        return verdict(answer == correct and 0 <= answer < len(options))
    # 5. bool / list / dict 等其它类型 → fail（不崩溃）
    return verdict(False)


def recommend_difficulty(history: list[dict]) -> int:
    """难度推荐：无历史→N1；最近 fail→降 1 级(≥0)；最近两条同难度 pass→升 1 级(≤3)；否则保持。"""
    if not isinstance(history, list):
        raise ValueError("history 必须是 list")
    for item in history:
        if not isinstance(item, dict):
            raise ValueError("history 元素必须是 dict")
        if item.get("result") not in ("pass", "fail"):
            raise ValueError("history.result 必须是 pass/fail")
        diff = item.get("difficulty")
        if isinstance(diff, bool) or not isinstance(diff, int) or not 0 <= diff <= 3:
            raise ValueError("history.difficulty 必须是 0-3 的 int")
    if not history:
        return 1
    current = history[-1]["difficulty"]
    if history[-1]["result"] == "fail":
        return max(0, current - 1)
    if len(history) >= 2 \
            and history[-2]["difficulty"] == current \
            and history[-2]["result"] == "pass":
        return min(3, current + 1)
    return current


def confirm_acceptance(task: dict, checklist: list[bool]) -> bool:
    """验收清单确认：产出物任务全部勾选才算通过。"""
    if not isinstance(task, dict):
        raise ValueError("task 必须是 dict")
    acceptance = task.get("acceptance")
    if not isinstance(acceptance, list) or not acceptance:
        raise ValueError("task.acceptance 必须是非空 list")
    if not isinstance(checklist, list) \
            or any(not isinstance(x, bool) for x in checklist):
        raise ValueError("checklist 必须是 bool list")
    if len(checklist) != len(acceptance):
        raise ValueError("checklist 长度必须等于 acceptance 长度")
    return all(checklist)
