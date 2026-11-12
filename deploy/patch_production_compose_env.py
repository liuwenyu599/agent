#!/usr/bin/env python3
"""为生产 compose 的 api.environment 补齐模型/并发变量透传（幂等、可重复跑）。

背景：线上 ``/opt/justice-office/deploy/docker-compose.yml`` 的 ``api`` 服务用
``environment:`` 显式白名单（没有 env_file），凡是没列出的键，``.env`` 里配了
也进不了容器，代码会静默使用默认值。2026-11-12 发现的缺失键包括
PPT_MODEL_URLS / PPT_MODEL_MAX_CONCURRENCY / PPT_COMPOSITION_PARALLEL /
WEB_THREADPOOL_TOKENS 等，会导致多副本分流与并发灰度「看起来没反应」。

用法（服务器 root 执行，AI 不代执行）::

    python3 deploy/patch_production_compose_env.py \
        /opt/justice-office/deploy/docker-compose.yml
    docker compose -f /opt/justice-office/deploy/docker-compose.yml config >/dev/null

脚本只做三件事：备份原文件、在 ``PPT_MODEL_NAME:`` 或 ``PPT_MODEL_URL:`` 锚点
后插入缺失键、打印清单。不改动已有行，不碰其它服务，不重启任何容器。
"""
from __future__ import annotations

import datetime
import pathlib
import re
import shutil
import sys

# 与 deploy/production.docker-compose.yml 的 api.environment 段保持一致
KEYS: list[tuple[str, str]] = [
    ("MODEL_SERVICE_URLS", "${MODEL_SERVICE_URLS:-}"),
    ("MODEL_MAX_CONCURRENCY", "${MODEL_MAX_CONCURRENCY:-4}"),
    ("MODEL_USER_MAX_CONCURRENCY", "${MODEL_USER_MAX_CONCURRENCY:-2}"),
    ("MODEL_USER_MAX_PENDING", "${MODEL_USER_MAX_PENDING:-8}"),
    ("MODEL_HEALTH_TIMEOUT", "${MODEL_HEALTH_TIMEOUT:-5}"),
    ("MODEL_FAILOVER_COOLDOWN", "${MODEL_FAILOVER_COOLDOWN:-15}"),
    ("VISION_MODEL_API_KEY", "${VISION_MODEL_API_KEY:-}"),
    ("VISION_MODEL_TIMEOUT", "${VISION_MODEL_TIMEOUT:-180}"),
    ("LONG_FORM_MODEL_URLS", "${LONG_FORM_MODEL_URLS:-}"),
    ("LONG_FORM_MODEL_NAME", "${LONG_FORM_MODEL_NAME:-}"),
    ("PPT_MODEL_URLS", "${PPT_MODEL_URLS:-}"),
    ("PPT_MODEL_API_KEY", "${PPT_MODEL_API_KEY:-}"),
    ("PPT_MODEL_TIMEOUT", "${PPT_MODEL_TIMEOUT:-300}"),
    ("PPT_MODEL_MAX_CONCURRENCY", "${PPT_MODEL_MAX_CONCURRENCY:-2}"),
    ("PPT_MODEL_SLOT_TIMEOUT", "${PPT_MODEL_SLOT_TIMEOUT:-300}"),
    ("PPT_COMPOSITION_PARALLEL", "${PPT_COMPOSITION_PARALLEL:-1}"),
    ("PPT_QUEUE_MAX", "${PPT_QUEUE_MAX:-50}"),
    ("PPT_QUEUE_TIMEOUT", "${PPT_QUEUE_TIMEOUT:-1800}"),
    ("WEB_THREADPOOL_TOKENS", "${WEB_THREADPOOL_TOKENS:-120}"),
]

_ANCHORS = ("PPT_MODEL_NAME", "PPT_MODEL_URL", "MODEL_NAME")


def _has_key(text: str, key: str) -> bool:
    # 只认真正的 YAML 映射行，忽略注释文本里提到的键名
    return re.search(rf"^\s+{re.escape(key)}:\s", text, re.M) is not None


def main(path: str) -> int:
    target = pathlib.Path(path)
    if not target.is_file():
        print(f"ERROR: 文件不存在: {target}", file=sys.stderr)
        return 2
    # 二进制读写 + 沿用原文件换行符：避免 Windows CRLF 污染 Linux compose 文件
    raw = target.read_bytes()
    text = raw.decode("utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    missing = [(k, v) for k, v in KEYS if not _has_key(text, k)]
    if not missing:
        print(f"OK: {target} 已包含全部 {len(KEYS)} 个键，无需修改（幂等退出）")
        return 0

    lines = text.splitlines(keepends=True)
    anchor_idx = None
    for anchor in _ANCHORS:
        for i, line in enumerate(lines):
            if re.match(rf"^\s+{re.escape(anchor)}:\s", line):
                anchor_idx = i
                break
        if anchor_idx is not None:
            break
    if anchor_idx is None:
        print("ERROR: 找不到 api.environment 锚点，拒绝盲改；请人工核对 compose 文件",
              file=sys.stderr)
        return 3

    indent = re.match(r"^(\s+)", lines[anchor_idx]).group(1)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = target.with_name(target.name + f".bak-env-{stamp}")
    shutil.copy2(target, backup)

    insertion = "".join(f"{indent}{k}: {v}{newline}" for k, v in missing)
    lines.insert(anchor_idx + 1, insertion)
    target.write_bytes("".join(lines).encode("utf-8"))

    print(f"备份: {backup}")
    print(f"在 {anchor_idx + 1} 行后插入 {len(missing)} 个键:")
    for k, _ in missing:
        print(f"  + {k}")
    print("下一步: docker compose -f <该文件> config >/dev/null && "
          "docker compose -f <该文件> up -d --no-deps api")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(1)
    raise SystemExit(main(sys.argv[1]))
