"""Guard the job-scoped MCP execution boundary before sandbox tools run.

Installed on AgentEnv.tool_execute, outside its broad exception handler so a
second deterministic failure terminates the agent loop instead of retrying.
"""
import ast
import json
import re
import shlex
import tokenize
from collections import Counter
from pathlib import Path

ABORT = "PPT_PYTHON_GUARD_ABORT"


def preflight(workspace, name, arguments):
    arguments = arguments or {}
    sources = []
    if name == "write_file" and str(arguments.get("path", "")).endswith(".py"):
        sources.append((arguments["path"], arguments.get("content", "")))
    elif name == "execute_command":
        if not Path(workspace).is_dir():
            return "Python preflight failed: job workspace is not locally accessible."
        # Scan the job workspace at the execution boundary, including scripts
        # created by edit_file and shell commands. Never execute to validate.
        for path in sorted(Path(workspace).rglob("*.py")):
            if path.is_symlink() or not path.resolve().is_relative_to(Path(workspace).resolve()):
                continue
            with tokenize.open(path) as source:
                sources.append((str(path), source.read()))
        command = str(arguments.get("command", arguments.get("cmd", "")))
        if re.search(r"\bpython(?:3(?:\.\d+)?)?\b", command) and "<<" in command:
            return "Python heredoc is not supported; use write_file for a .py script."
        try:
            words = shlex.split(command)
        except ValueError:
            words = []
        for index, word in enumerate(words):
            if not re.fullmatch(r"python(?:3(?:\.\d+)?)?", Path(word).name):
                continue
            tail = words[index + 1:]
            if "-c" in tail and tail.index("-c") + 1 < len(tail):
                sources.append(("<python -c>", tail[tail.index("-c") + 1]))
            for candidate in tail:
                if candidate.endswith(".py"):
                    path = Path(candidate)
                    if not path.is_absolute():
                        path = Path(workspace) / path
                    if path.is_file():
                        with tokenize.open(path) as source:
                            sources.append((str(path), source.read()))
    for filename, source in sources:
        try:
            ast.parse(source, filename=filename)
        except SyntaxError as error:
            return (f"SyntaxError: {error.msg}; line {error.lineno}. "
                    "检查字符串字面量中的转义；换行请用 chr(10) 或三引号。")
    return None


def fingerprint(text):
    # Ignore volatile paths, line numbers and addresses, retaining error kind.
    text = re.sub(r'File "[^"]+", line \d+', 'File <script>, line <n>', text)
    text = re.sub(r"\bline \d+|0x[0-9a-fA-F]+", "<n>", text)
    return text.strip()


def install(env_class):
    if getattr(env_class.tool_execute, "_judicial_python_guard", False):
        return
    original = env_class.tool_execute

    async def guarded(self, tool_call):
        from deeppresenter.utils.typings import ChatMessage, Role

        if not hasattr(self, "_judicial_guard_errors"):
            self._judicial_guard_errors = Counter()
        if getattr(self, "_judicial_guard_aborted", False):
            raise RuntimeError(f"{ABORT}: job already aborted")
        arguments = json.loads(tool_call.function.arguments or "{}")
        error = preflight(self.workspace, tool_call.function.name, arguments)
        if error:
            observation = ChatMessage(role=Role.TOOL, content=error,
                                      tool_call_id=tool_call.id, is_error=True)
        else:
            observation = await original(self, tool_call)
        if observation.is_error:
            key = fingerprint(observation.text)
            self._judicial_guard_errors[key] += 1
            if self._judicial_guard_errors[key] >= 2:
                self._judicial_guard_aborted = True
                for task in getattr(self, "_async_tool_tasks", {}).values():
                    task.cancel()
                raise RuntimeError(f"{ABORT}: 同一执行错误已出现两次，任务已中止。{key[:500]}")
        return observation

    guarded._judicial_python_guard = True
    env_class.tool_execute = guarded
