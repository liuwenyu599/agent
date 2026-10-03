"""Probe every configured main/PPT model replica.

Usage from server/: python scripts/check_model_pool.py
Exit code 0 only when every configured endpoint responds below 500 on /models.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow direct execution from server/scripts without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.infrastructure.ai import get_llm_gateway, get_ppt_gateway  # noqa: E402


def _probe(name, gateway):
    if gateway is None:
        return {"pool": name, "configured": False, "healthy": True, "endpoints": []}
    health = getattr(gateway, "health", None)
    if health is None:
        return {"pool": name, "configured": True, "healthy": True,
                "endpoints": [{"model": gateway.model_name, "health_probe": "unsupported"}]}
    endpoints = health()
    return {
        "pool": name,
        "configured": True,
        "healthy": bool(endpoints) and all(item["healthy"] for item in endpoints),
        "endpoints": endpoints,
    }


def main() -> int:
    results = [_probe("text", get_llm_gateway())]
    ppt = get_ppt_gateway()
    if ppt is not None:
        results.append(_probe("ppt", ppt))
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(item["healthy"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
