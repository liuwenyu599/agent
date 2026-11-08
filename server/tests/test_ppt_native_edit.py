import io
import zipfile

import pytest
from pptx import Presentation
from pptx.util import Inches, Pt

from app.application.ppt import native_edit


def test_native_edit_only_changes_target_slide_xml():
    presentation = Presentation()
    for title in ("原始第一页", "第二页不变"):
        slide = presentation.slides.add_slide(presentation.slide_layouts[6])
        box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(1))
        run = box.text_frame.paragraphs[0].add_run()
        run.text = title
        run.font.size = Pt(28)
        slide.notes_slide.notes_text_frame.text = "需要保留的备注"
    presentation.slides.add_slide(presentation.slide_layouts[6])
    stream = io.BytesIO()
    presentation.save(stream)
    original = stream.getvalue()
    outline, manifest = native_edit.read_source(original)
    assert len(outline["slides"]) == 3
    unchanged = native_edit.render(original, manifest, outline)
    with zipfile.ZipFile(io.BytesIO(original)) as before, zipfile.ZipFile(io.BytesIO(unchanged)) as after:
        assert all(before.read(name) == after.read(name) for name in before.namelist())
    outline["slides"][0]["title"] = "修改后的第一页"
    result = native_edit.render(original, manifest, outline)
    with zipfile.ZipFile(io.BytesIO(original)) as before, zipfile.ZipFile(io.BytesIO(result)) as after:
        changed = [name for name in before.namelist() if before.read(name) != after.read(name)]
    assert changed == [manifest[0]["part"]]
    parsed = Presentation(io.BytesIO(result))
    assert parsed.slides[0].shapes[0].text == "修改后的第一页"
    assert parsed.slides[0].shapes[0].text_frame.paragraphs[0].runs[0].font.size.pt == 28
    outline["slides"].reverse()
    with pytest.raises(ValueError):
        native_edit.render(original, manifest, outline)
