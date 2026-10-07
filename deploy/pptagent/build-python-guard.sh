#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
BASE_IMAGE=${BASE_IMAGE:-deeppresenter-host:latest}
GUARDED_IMAGE=${GUARDED_IMAGE:-deeppresenter-host:python-guard-v1}
# Preserve and verify the frozen production baseline before adding one layer.
HOST_IMAGE="$BASE_IMAGE" bash "$SCRIPT_DIR/verify-patched-images.sh"
docker build --pull=false --build-arg "BASE_IMAGE=$BASE_IMAGE" \
  -f "$SCRIPT_DIR/Dockerfile.python-guard" -t "$GUARDED_IMAGE" "$SCRIPT_DIR"
docker run --rm --entrypoint python "$GUARDED_IMAGE" -c '
from deeppresenter.agents.env import AgentEnv
assert AgentEnv.tool_execute._judicial_python_guard
from deeppresenter.agents.judicial_python_guard import preflight
assert "SyntaxError" in preflight("/tmp", "write_file", {"path": "test.py", "content": "print("})
assert "SyntaxError" in preflight("/tmp", "write_file", {"path": "test.py", "content": "draw(color=1, color=2)"})
'
HOST_IMAGE="$GUARDED_IMAGE" bash "$SCRIPT_DIR/verify-patched-images.sh"
echo "Guard verified: $GUARDED_IMAGE. Configure the host to use this image and restart the host."
