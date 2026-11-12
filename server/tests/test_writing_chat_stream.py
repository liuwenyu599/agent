"""A multi-turn writing reply always ends the event stream with a result."""

import asyncio
import json
from types import SimpleNamespace

from app.interfaces.writing_tasks import TaskChatRequest, task_chat_stream


def _events(service):
    async def run():
        response = await task_chat_stream(
            "task-1", TaskChatRequest(message="继续修改"),
            user=SimpleNamespace(id="user-1"), svc=service)
        chunks = [chunk async for chunk in response.body_iterator]
        return [json.loads(chunk.removeprefix("data: ")) for chunk in chunks]
    return asyncio.run(run())


def test_chat_stream_emits_stage_then_done_with_reply():
    class Service:
        async def chat_async(self, task_id, user_id, message):
            assert (task_id, user_id, message) == ("task-1", "user-1", "继续修改")
            return {"reply": "已修改第二段", "content_changed": True}

    events = _events(Service())
    assert events[0]["type"] == "stage"
    assert events[-1] == {"type": "done", "data": {
        "reply": "已修改第二段", "content_changed": True}}


def test_chat_stream_reports_failure_and_closes():
    class Service:
        async def chat_async(self, *_):
            raise RuntimeError("internal secret")

    events = _events(Service())
    assert events[-1]["type"] == "error"
    assert "internal secret" not in events[-1]["message"]
