"""Large gallery photographs should not dominate exported presentations."""
import io
import sys
from pathlib import Path
from zipfile import ZipFile

from PIL import Image
from pptx import Presentation

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.application.ppt import ppt_engine


def _slide(path: Path):
    return {"type": "content", "title": "现场研讨", "points": ["明确工作安排"],
            "_image": {"file_path": str(path), "caption": "会议照片"}}


def test_large_opaque_gallery_png_is_downsampled_and_embedded_as_jpeg(tmp_path):
    photo = tmp_path / "large.png"
    Image.effect_noise((2400, 1800), 55).convert("RGB").save(photo)
    template = {"colors": ppt_engine.DEFAULT_COLORS,
                "layouts": ppt_engine.DEFAULT_LAYOUTS, "font": "微软雅黑"}
    output = ppt_engine.render_pptx({"slides": [_slide(photo)]}, template,
                                     adaptive=True)
    result = Presentation(io.BytesIO(output)).slides[0]
    embedded = [shape.image for shape in result.shapes if shape.shape_type == 13]
    assert embedded
    assert embedded[0].ext == "jpg"
    assert len(embedded[0].blob) < photo.stat().st_size / 5
    assert max(embedded[0].size) < 2400


def test_alpha_gallery_image_remains_png(tmp_path):
    photo = tmp_path / "transparent.png"
    Image.new("RGBA", (2400, 1800), (50, 100, 150, 130)).save(photo)
    template = {"colors": ppt_engine.DEFAULT_COLORS,
                "layouts": ppt_engine.DEFAULT_LAYOUTS, "font": "微软雅黑"}
    output = ppt_engine.render_pptx({"slides": [_slide(photo)]}, template,
                                     adaptive=True)
    result = Presentation(io.BytesIO(output)).slides[0]
    embedded = [shape.image for shape in result.shapes if shape.shape_type == 13]
    assert embedded and embedded[0].ext == "png"


def test_removed_template_example_photo_does_not_remain_in_export(tmp_path):
    photo = tmp_path / "source.png"
    Image.effect_noise((2400, 1800), 55).convert("RGB").save(photo)
    source = Presentation()
    page = source.slides.add_slide(source.slide_layouts[6])
    page.shapes.add_picture(str(photo), 914400, 1371600, 7315200, 4114800)
    stream = io.BytesIO()
    source.save(stream)
    base = stream.getvalue()
    library = ppt_engine.analyze_template(base)["layouts"]
    result = ppt_engine.build_pptx_learned(
        {"slides": [{"type": "content", "title": "工作安排",
                     "points": ["明确职责分工"]}]},
        {"colors": ppt_engine.DEFAULT_COLORS, "font": "微软雅黑"},
        base, library, warnings=[])
    with ZipFile(io.BytesIO(result)) as archive:
        media = [name for name in archive.namelist()
                 if name.startswith("ppt/media/")]
    assert not media


def test_large_page_media_gets_a_warning_without_blocking_export(tmp_path):
    photo = tmp_path / "heavy.png"
    Image.effect_noise((2400, 1800), 55).convert("RGB").save(photo)
    source = Presentation()
    page = source.slides.add_slide(source.slide_layouts[6])
    page.shapes.add_picture(str(photo), 914400, 914400, 7315200, 4114800)
    stream = io.BytesIO()
    source.save(stream)
    warnings = ppt_engine.export_media_warnings(stream.getvalue())
    assert any("第1页" in warning and "2 MB" in warning for warning in warnings)
