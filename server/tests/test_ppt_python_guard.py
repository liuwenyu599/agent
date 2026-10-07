import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

GUARD_PATH = Path(__file__).resolve().parents[2] / "deploy/pptagent/python_guard.py"
spec = importlib.util.spec_from_file_location("ppt_python_guard", GUARD_PATH)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def test_preflight_handles_decoded_newline_before_execution(tmp_path):
    assert "SyntaxError" in guard.preflight(tmp_path, "write_file", {
        "path": "chart.py", "content": 'label = "a\nb"'})
    assert guard.preflight(tmp_path, "write_file", {
        "path": "chart.py", "content": 'label = "a\\nb"'}) is None
    assert guard.preflight(tmp_path, "write_file", {
        "path": "chart.py", "content": 'label = "a" + chr(10) + "b"'}) is None


def test_preflight_rejects_duplicate_keyword_arguments(tmp_path):
    error = guard.preflight(tmp_path, "write_file", {
        "path": "slide.py", "content": "draw(color='red', color='blue')"})
    assert "SyntaxError" in error
    assert "keyword argument repeated" in error


def test_preflight_checks_edited_script_and_inline_python(tmp_path):
    script = tmp_path / "chart.py"
    script.write_text('label = "a\nb"')
    assert "SyntaxError" in guard.preflight(tmp_path, "execute_command", {"command": "python chart.py"})
    script.unlink()
    assert "SyntaxError" in guard.preflight(tmp_path, "execute_command", {"command": "python -c 'print('"})


def test_guard_aborts_second_error_and_is_job_scoped(tmp_path, monkeypatch):
    class Message:
        def __init__(self, content="", is_error=False, **kwargs):
            self.text = content
            self.is_error = is_error

    module = ModuleType("deeppresenter.utils.typings")
    module.ChatMessage = Message
    module.Role = SimpleNamespace(TOOL="tool")
    monkeypatch.setitem(sys.modules, "deeppresenter.utils.typings", module)

    class Env:
        workspace = tmp_path
        calls = 0

        async def tool_execute(self, tool_call):
            self.calls += 1
            return Message()

    guard.install(Env)
    env = Env()
    call = SimpleNamespace(id="1", function=SimpleNamespace(name="write_file", arguments=json.dumps({
        "path": "chart.py", "content": 'label = "a\nb"'})))
    assert asyncio.run(env.tool_execute(call)).is_error
    with pytest.raises(RuntimeError, match=guard.ABORT):
        asyncio.run(env.tool_execute(call))
    assert env.calls == 0
    assert asyncio.run(Env().tool_execute(call)).is_error


def test_repeat_fingerprint_ignores_line_drift():
    assert guard.fingerprint("SyntaxError: unterminated string; line 1") == guard.fingerprint(
        "SyntaxError: unterminated string; line 12")
