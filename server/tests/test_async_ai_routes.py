"""Regression contract for item 6: model HTTP must not occupy FastAPI worker threads."""
import inspect
from pathlib import Path

from app.interfaces import chat as chat_routes
from app.interfaces import writing_tasks as writing_routes
from app.infrastructure.ai.qwen import QwenGateway


def test_chat_send_is_native_async_route():
    assert inspect.iscoroutinefunction(chat_routes.chat)


def test_writing_model_routes_are_native_async():
    assert inspect.iscoroutinefunction(writing_routes.create_task)
    assert inspect.iscoroutinefunction(writing_routes.plan_task)
    assert inspect.iscoroutinefunction(writing_routes.task_chat)
    assert inspect.iscoroutinefunction(writing_routes.task_draft)
    assert inspect.iscoroutinefunction(writing_routes.task_draft_stream)
    assert inspect.iscoroutinefunction(writing_routes.task_revise)
    assert inspect.iscoroutinefunction(writing_routes.upload_task_images)
    assert inspect.iscoroutinefunction(writing_routes.upload_task_materials)


def test_qwen_transport_is_httpx_async_not_requests():
    source = Path(inspect.getsourcefile(QwenGateway)).read_text(encoding="utf-8")
    assert "httpx.AsyncClient" in source
    assert "requests.post" not in source
    assert "import requests" not in source
    assert "asyncio.wrap_future" in source


def test_writing_image_route_prefers_async_model_transport():
    source = inspect.getsource(writing_routes._store_task_materials)
    assert "run_in_threadpool" not in source
    assert "acomplete" in source
