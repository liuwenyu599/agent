"""One writing-task batch accepts documents and images and binds both."""

import asyncio
from types import SimpleNamespace

from app.interfaces import writing_tasks


def test_mixed_materials_are_bound_to_task_session(monkeypatch):
    class Attachments:
        def __init__(self):
            self.bound = None

        async def save_and_parse(self, file, user_id, db):
            is_image = file.filename.endswith(".png")
            return SimpleNamespace(
                id=file.filename, filename=file.filename,
                kind="image" if is_image else "doc",
                file_path="", text_content="识别文字" if is_image else "文档正文",
                parse_status="ok", parse_note="OCR识别" if is_image else "",
            )

        def bind_to_session(self, ids, session_id, user_id, db):
            self.bound = (ids, session_id, user_id)

    attachments = Attachments()
    task = SimpleNamespace(session_id="session-1")
    svc = SimpleNamespace(_get_owned=lambda *args: task, attachments=attachments)
    monkeypatch.setattr(writing_tasks, "get_vision_gateway", lambda: None)
    files = [SimpleNamespace(filename="report.docx"), SimpleNamespace(filename="scan.png")]
    result = asyncio.run(writing_tasks._store_task_materials(
        "task-1", files, SimpleNamespace(id="user-1"), svc, object(), image_only=False))
    assert [item["kind"] for item in result["items"]] == ["doc", "image"]
    assert attachments.bound == (["report.docx", "scan.png"], "session-1", "user-1")
