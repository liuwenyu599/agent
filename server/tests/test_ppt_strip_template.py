"""deploy/strip_ppt_template.py 的离线单测：不碰数据库、不碰线上生成链路。"""
from __future__ import annotations

import importlib.util
import io
import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image
from pptx import Presentation
from pptx.util import Inches

_SCRIPT = (Path(__file__).resolve().parents[2] / "deploy"
           / "strip_ppt_template.py")
_spec = importlib.util.spec_from_file_location("strip_ppt_template", _SCRIPT)
strip = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(strip)

SECRET_TEXT = "白云区司法局二〇二六年度工作总结"


def _sample_deck() -> bytes:
    """造一份 3 页、含中文正文与一张只被内容页引用的图片的 pptx。"""
    prs = Presentation()
    for i in range(3):
        slide = prs.slides.add_slide(prs.slide_layouts[1 if i else 0])
        slide.shapes.title.text = f"{SECRET_TEXT} 第{i + 1}页"
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 0, 0)).save(buf, format="PNG")
    prs.slides[0].shapes.add_picture(io.BytesIO(buf.getvalue()),
                                     Inches(1), Inches(1), Inches(1), Inches(1))
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()


def _xml_text(blob: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        return "\n".join(zf.read(n).decode("utf-8", "ignore")
                         for n in zf.namelist() if n.endswith(".xml"))


class TestStripPptTemplate:
    def test_zero_slides_but_template_system_unchanged(self):
        source = _sample_deck()
        base = strip.strip_template_bytes(source)
        report = strip.verify_strip(source, base)

        src, dst = report["source"], report["base"]
        assert src["slides"] == 3 and dst["slides"] == 0
        for key in ("masters", "layouts", "width", "height", "accent1"):
            assert src[key] == dst[key], key
        assert dst["slide_parts"] == 0 and dst["note_parts"] == 0
        # 内容页文字与只被内容页引用的图片都不能残留在底板上
        assert SECRET_TEXT not in _xml_text(base)
        assert dst["media_parts"] == 0 and src["media_parts"] == 1
        # 输入字节不被就地修改
        assert len(Presentation(io.BytesIO(source)).slides) == 3

    def test_base_can_host_a_new_slide(self):
        base = strip.strip_template_bytes(_sample_deck())
        prs = Presentation(io.BytesIO(base))
        layout = prs.slide_layouts[1]
        slide = prs.slides.add_slide(layout)
        slide.shapes.title.text = "新成稿第一页"
        out = io.BytesIO()
        prs.save(out)
        result = Presentation(io.BytesIO(out.getvalue()))
        assert len(result.slides) == 1
        assert result.slides[0].shapes.title.text == "新成稿第一页"

    def test_bad_input_raises_strip_error(self):
        with pytest.raises(Exception):
            strip.strip_template_bytes(b"not a pptx at all")

    def test_dry_run_does_not_write_and_force_overwrites(self, tmp_path):
        source = tmp_path / "template.pptx"
        source.write_bytes(_sample_deck())
        output = tmp_path / "out" / "base.pptx"

        report = strip.strip_file(source, output, dry_run=True)
        assert report["dry_run"] is True and not output.exists()

        strip.strip_file(source, output)
        assert output.is_file()
        assert len(Presentation(str(output)).slides) == 0

        with pytest.raises(strip.StripError, match="输出已存在"):
            strip.strip_file(source, output)
        strip.strip_file(source, output, force=True)
        assert output.is_file()

    def test_cli_json_report_for_a_single_file(self, tmp_path, capsys):
        source = tmp_path / "template.pptx"
        source.write_bytes(_sample_deck())
        output = tmp_path / "base.pptx"
        code = strip.main([str(source), "-o", str(output), "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert code == 0 and not payload["errors"]
        assert payload["reports"][0]["base"]["slides"] == 0
        assert output.is_file()
