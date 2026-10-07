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


def test_unrelated_command_is_not_blocked_by_stale_broken_script(tmp_path):
    """与 Python 无关的命令不应被工作区里残留的坏 .py 拦下。

    回归：早期实现对任何 execute_command 都 rglob 整个工作区并校验全部 .py，
    一个半截残留脚本会让 ls/cd 全返回 SyntaxError，而相同错误连续两次即中止，
    于是两次 ls 就能把 agent 打死。
    """
    (tmp_path / "stale.py").write_text("def broken(:\n")
    for command in ["ls -la", "cd /tmp", "mkdir out", "cat stale.py"]:
        assert guard.preflight(tmp_path, "execute_command", {"command": command}) is None, command
    # 目标脚本本身坏掉时仍必须拦
    assert "SyntaxError" in guard.preflight(
        tmp_path, "execute_command", {"command": "python stale.py"})


def test_only_the_executed_script_is_validated(tmp_path):
    """命令点名要跑的那份脚本要校验；同目录其他坏文件不应牵连。"""
    (tmp_path / "stale.py").write_text("def broken(:\n")
    good = tmp_path / "chart.py"
    good.write_text("print('ok')")
    assert guard.preflight(tmp_path, "execute_command", {"command": "python chart.py"}) is None
    assert "SyntaxError" in guard.preflight(
        tmp_path, "execute_command", {"command": "python stale.py"})


def test_python_dash_m_resolves_module_file(tmp_path):
    (tmp_path / "broken_mod.py").write_text("def broken(:\n")
    assert "SyntaxError" in guard.preflight(
        tmp_path, "execute_command", {"command": "python -m broken_mod"})


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
