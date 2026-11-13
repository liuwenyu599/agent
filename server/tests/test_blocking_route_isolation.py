"""Regression tests for blocking model calls behind FastAPI async routes.

QwenGateway is intentionally synchronous today (requests.post). Endpoints that enter
model-backed upload workflows must therefore be normal ``def`` routes so FastAPI runs
the whole call in its worker thread pool instead of blocking the main event loop.
"""
import inspect

from app.interfaces import format_check as format_routes
from app.interfaces import ppt as ppt_routes


class _FormatService:
    async def check_upload(self, file, user, use_ai=True, rule_ids=None):
        return {"ok": True, "use_ai": use_ai, "rule_ids": rule_ids}


class _PPTService:
    async def analyze_materials(self, files, user):
        return {"ok": True, "count": len(files)}

    async def outline_from_doc(self, file, topic, audience, scene, slide_count, user,
                               structure="auto"):
        return {"ok": True, "topic": topic, "slide_count": slide_count}


def test_format_check_model_backed_upload_is_sync_route():
    assert not inspect.iscoroutinefunction(format_routes.check_document)
    result = format_routes.check_document(
        file=object(), user=object(), svc=_FormatService(),
        use_ai=True, rule_ids="r1,r2",
    )
    assert result == {"ok": True, "use_ai": True, "rule_ids": "r1,r2"}


def test_ppt_material_analysis_is_sync_route():
    assert not inspect.iscoroutinefunction(ppt_routes.analyze_materials)
    result = ppt_routes.analyze_materials(
        files=[object(), object()], user=object(), svc=_PPTService()
    )
    assert result == {"ok": True, "count": 2}


def test_ppt_outline_from_doc_is_sync_route():
    assert not inspect.iscoroutinefunction(ppt_routes.outline_from_doc)
    result = ppt_routes.outline_from_doc(
        file=object(), topic="社区矫正", audience="", scene="",
        slide_count=10, user=object(), svc=_PPTService(),
    )
    assert result == {"ok": True, "topic": "社区矫正", "slide_count": 10}


def test_outline_from_doc_runs_sync_chain_off_event_loop():
    """文档导入的同步大纲链路不得在 running loop 内执行。

    路由用 asyncio.run 驱动 service，而 _do_outline 整条链路调的是同步
    QwenGateway.complete()；新版同步桥会在 event loop 内直接抛 RuntimeError，
    因此必须把它挪到 asyncio.to_thread 的无 loop 工作线程，否则线上 500。
    """
    import asyncio

    from app.application.ppt.service import PPTService

    seen = {}

    class _File:
        filename = "m.docx"

        async def read(self):
            return b"data"

    def fake_do_outline(*args, **kwargs):
        try:
            asyncio.get_running_loop()
            seen["in_loop"] = True
        except RuntimeError:
            seen["in_loop"] = False
        seen["structure"] = kwargs.get("structure")
        return {"ok": True}

    svc = object.__new__(PPTService)
    svc._do_outline = fake_do_outline
    svc._extract_any = staticmethod(lambda name, data: "材料正文")

    out = asyncio.run(svc.outline_from_doc(
        _File(), "社区矫正", "", "", 10, object(), structure="方案"))
    assert out == {"ok": True}
    assert seen.get("in_loop") is False, "同步大纲链路仍在 event loop 内"
    assert seen.get("structure") == "方案"
