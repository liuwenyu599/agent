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


def _touches_python(command: str) -> bool:
    """命令是否会执行 Python。只有这类命令才需要做源码预检。"""
    if re.search(r"\bpython(?:3(?:\.\d+)?)?\b", command):
        return True
    try:
        return any(word.endswith(".py") for word in shlex.split(command))
    except ValueError:
        return ".py" in command


def _read_source(workspace: Path, path: Path):
    """读工作区内的源码；拒绝软链与越界路径。返回 None 表示不该校验。"""
    try:
        if path.is_symlink() or not path.resolve().is_relative_to(workspace.resolve()):
            return None
        if not path.is_file():
            return None
        with tokenize.open(path) as source:
            return str(path), source.read()
    except (OSError, UnicodeDecodeError, SyntaxError):
        return None


def preflight(workspace, name, arguments):
    arguments = arguments or {}
    sources = []
    if name == "write_file" and str(arguments.get("path", "")).endswith(".py"):
        sources.append((arguments["path"], arguments.get("content", "")))
    elif name == "execute_command":
        root = Path(workspace)
        if not root.is_dir():
            return "Python preflight failed: job workspace is not locally accessible."
        command = str(arguments.get("command", arguments.get("cmd", "")))
        # 与 Python 无关的命令（ls / cd / mkdir ...）直接放行。
        # 早期实现会无条件 rglob 整个工作区的 *.py 并全部校验，导致一个残留的
        # 半截脚本让**任何**命令都返回 SyntaxError；而相同错误连续两次即触发
        # 任务中止，于是两次 ls 就能把整个 agent 打死——与守卫意图无关的误伤。
        if not _touches_python(command):
            return None
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
            # 只校验这条命令真正会执行的文件（含 edit_file / shell 生成的脚本，
            # 它们执行时必然出现在命令行里），而不是工作区里的任意 .py。
            for position, token in enumerate(tail):
                candidate = None
                if token.endswith(".py"):
                    candidate = Path(token)
                elif token == "-m" and position + 1 < len(tail):
                    candidate = root / (tail[position + 1].split(".")[-1] + ".py")
                if candidate is not None:
                    resolved = _read_source(root, candidate if candidate.is_absolute()
                                           else root / candidate)
                    if resolved:
                        sources.append(resolved)
    for filename, source in sources:
        try:
            tree = ast.parse(source, filename=filename)
            # ast.parse accepts duplicate call keywords; compilation catches
            # that SyntaxError without running any user script.
            compile(tree, filename, "exec")
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
