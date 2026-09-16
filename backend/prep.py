"""备课输入服务：把可核查教学事实与 SQLite 读写分开。"""
from __future__ import annotations

from backend import store


FALLBACK_PATHS = ("replace_material", "paste_content", "create_original_question")


def _text(value, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} 必须是非空字符串")
    return value.strip()


def _texts(value, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{field} 必须是非空字符串列表")
    return [item.strip() for item in value]


def _pages(value, field: str) -> list[int]:
    if (not isinstance(value, list) or not value or any(isinstance(item, bool) or not isinstance(item, int) or item < 1
                                                        for item in value) or len(set(value)) != len(value)):
        raise ValueError(f"{field} 必须是不重复的正页码列表")
    return value


def _student_or_error(student_id: int) -> dict:
    student = store.get_student_record(student_id)
    if student is None:
        raise ValueError(f"student {student_id} 不存在")
    return student


def _material_or_error(material_id: int) -> dict:
    material = store.get_reference_material_record(material_id)
    if material is None:
        raise ValueError(f"reference material {material_id} 不存在")
    return material


def student_profile(data: dict) -> dict:
    status = data.get("school_progress_status")
    progress = data.get("school_progress")
    if status not in ("known", "unknown"):
        raise ValueError("school_progress_status 必须是 known 或 unknown")
    if status == "unknown" and progress is not None:
        raise ValueError("school_progress_status 为 unknown 时不得填写或推断 school_progress")
    if status == "known":
        progress = _text(progress, "school_progress")
    record = {
        "name": _text(data.get("name"), "name"),
        "grade": _text(data.get("grade"), "grade"),
        "subject": _text(data.get("subject"), "subject"),
        "observed_errors": _texts(data.get("observed_errors"), "observed_errors"),
        "independent_tasks": _texts(data.get("independent_tasks"), "independent_tasks"),
        "school_progress_status": status,
        "school_progress": progress,
    }
    return store.get_student_record(store.create_student_record(record))


def _validate_read_pages(value, selected_pages: list[int]) -> list[dict]:
    if not isinstance(value, list):
        raise ValueError("read_pages 必须是列表")
    pages = []
    seen = set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("read_pages 项必须是对象")
        page = item.get("page")
        if isinstance(page, bool) or not isinstance(page, int) or page not in selected_pages or page in seen:
            raise ValueError("read_pages.page 必须是范围内且不重复的页码")
        pages.append({"page": page, "content": _text(item.get("content"), "read_pages.content")})
        seen.add(page)
    return pages


def _validate_statements(value, read_pages: list[dict]) -> list[dict]:
    if not isinstance(value, list):
        raise ValueError("statements 必须是列表")
    content_by_page = {item["page"]: item["content"] for item in read_pages}
    result = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("statements 项必须是对象")
        page = item.get("page")
        text = _text(item.get("text"), "statements.text")
        if page not in content_by_page:
            raise ValueError("材料表述只能来自实际读取到的页")
        if text not in content_by_page[page]:
            raise ValueError("材料表述必须能在已读取正文中定位")
        result.append({"topic": _text(item.get("topic"), "statements.topic"), "text": text, "page": page})
    return result


def material_view(material: dict) -> dict:
    return {**material, "fallback_paths": list(FALLBACK_PATHS)}


def reference_material(data: dict, source_kind: str = "file") -> dict:
    selected_pages = _pages(data.get("selected_pages"), "selected_pages")
    read_pages = _validate_read_pages(data.get("read_pages"), selected_pages)
    unread_pages = _pages(data.get("unread_pages"), "unread_pages") if data.get("unread_pages") else []
    if set(page["page"] for page in read_pages) & set(unread_pages):
        raise ValueError("同一页不能同时标为已读和未读")
    if set(page["page"] for page in read_pages) | set(unread_pages) != set(selected_pages):
        raise ValueError("选择范围内每一页都必须标记为已读或未读")
    statements = _validate_statements(data.get("statements", []), read_pages)
    record = {
        "title": _text(data.get("title"), "title"),
        "file_identifier": _text(data.get("file_identifier"), "file_identifier"),
        "source_kind": source_kind,
        "selected_pages": selected_pages,
        "usage_scope": _text(data.get("usage_scope"), "usage_scope"),
        "read_pages": read_pages,
        "unread_pages": unread_pages,
    }
    material_id = store.create_reference_material_record(record, statements)
    return material_view(_material_or_error(material_id))


def pasted_material(data: dict) -> dict:
    return reference_material({
        "title": data.get("title"), "file_identifier": "教师粘贴内容",
        "selected_pages": [1], "usage_scope": data.get("usage_scope"),
        "read_pages": [{"page": 1, "content": data.get("content")}], "unread_pages": [], "statements": [],
    }, source_kind="pasted")


def cite_material(material_id: int, page: int, locator: str) -> dict:
    material = _material_or_error(material_id)
    if isinstance(page, bool) or not isinstance(page, int):
        raise ValueError("page 必须是页码")
    locator = _text(locator, "locator")
    read_content = next((item["content"] for item in material["read_pages"] if item["page"] == page), None)
    if read_content is None:
        raise ValueError("不能引用未读取页或不存在的页")
    if locator not in read_content:
        raise ValueError("引用定位文字不在已读取正文中")
    return store.create_reference_citation_record(material_id, page, locator)


def select_material(student_id: int, material_id: int, data: dict) -> dict:
    _student_or_error(student_id)
    material = _material_or_error(material_id)
    selected_pages = _pages(data.get("selected_pages"), "selected_pages")
    if not set(selected_pages).issubset(material["selected_pages"]):
        raise ValueError("选择页必须属于材料已声明的范围")
    return store.create_material_selection_record(student_id, material_id, selected_pages,
                                                  _text(data.get("usage_scope"), "usage_scope"))


def material_selections(student_id: int) -> list[dict]:
    _student_or_error(student_id)
    return [{**selection, "material": material_view(selection["material"])}
            for selection in store.list_material_selection_records(student_id)]


def statements(topic: str | None = None) -> list[dict]:
    if topic is not None:
        topic = _text(topic, "topic")
    return store.list_reference_statements(topic)


def choose_statement(student_id: int, statement_id: int) -> dict:
    _student_or_error(student_id)
    statement = next((item for item in store.list_reference_statements() if item["id"] == statement_id), None)
    if statement is None:
        raise ValueError(f"reference statement {statement_id} 不存在")
    return store.choose_reference_statement_record(student_id, statement["topic"], statement_id)
