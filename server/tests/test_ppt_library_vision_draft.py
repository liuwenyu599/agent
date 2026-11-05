"""Vision descriptions are drafts, not automatic public-library publication."""
import asyncio
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "deploy"))

from analyze_ppt_library_images import PROMPT, build_draft  # noqa: E402


def test_vision_draft_uses_image_content_and_stays_disabled(tmp_path):
    Image.new("RGB", (640, 360), "red").save(tmp_path / "活动照片.png")

    class VisionGateway:
        async def acomplete(self, messages, **_kwargs):
            parts = messages[0]["content"]
            assert parts[0]["type"] == "text"
            assert parts[1]["type"] == "image_url"
            assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
            return ('{"caption":"室内活动现场，一名工作人员向群众展示资料",'
                    '"category":"法治宣传","tags":["室内活动","资料"],'
                    '"review_note":"无法确认具体活动名称"}')

    manifest, errors = asyncio.run(build_draft(tmp_path, VisionGateway()))
    assert not errors
    entry = manifest["images"][0]
    assert entry["caption"].startswith("室内活动现场")
    assert entry["category"] == "法治宣传"
    assert entry["enabled"] is False
    assert "待核对" in entry["review_note"]
    assert manifest["defaults"] == {"source": "", "license_note": ""}
    assert "不能只做 OCR" in PROMPT


def test_failed_vision_draft_does_not_invent_a_caption(tmp_path):
    Image.new("RGB", (640, 360), "blue").save(tmp_path / "未知场景.png")

    class BrokenGateway:
        async def acomplete(self, *_args, **_kwargs):
            raise RuntimeError("vision unavailable")

    manifest, errors = asyncio.run(build_draft(tmp_path, BrokenGateway()))
    assert len(errors) == 1
    assert manifest["images"][0]["caption"] == ""
    assert manifest["images"][0]["enabled"] is False
