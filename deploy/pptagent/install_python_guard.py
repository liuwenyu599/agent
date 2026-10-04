"""Install into the frozen, verified host image; fail on interface drift."""
import ast
import shutil
import sys
from pathlib import Path

target = Path(sys.argv[1])
source = target.read_text(encoding="utf-8")
tree = ast.parse(source)
env = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "AgentEnv")
method = next(node for node in env.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "tool_execute")
if [arg.arg for arg in method.args.args] != ["self", "tool_call"]:
    raise SystemExit("Unsupported AgentEnv.tool_execute signature; no patch applied")
shutil.copyfile(Path(__file__).with_name("python_guard.py"), target.with_name("judicial_python_guard.py"))
marker = "# judicial-python-guard-v1"
if marker not in source:
    source += ("\n" + marker + "\n"
               "from .judicial_python_guard import install as _install_python_guard\n"
               "_install_python_guard(AgentEnv)\n")
    ast.parse(source)
    target.write_text(source, encoding="utf-8")
