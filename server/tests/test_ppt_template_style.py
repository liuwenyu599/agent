from app.application.ppt.template_style import (read_template_reference,
                                                summarize_template_style)


def test_template_style_uses_typography_and_shapes_without_sample_content():
    template = {"layout_library": [{"detected_type": "content",
        "text_regions": [
            {"role": "title", "font_size": 32, "sample": "old title"},
            {"role": "body", "font_size": 20, "bold": False,
             "sample": "old factual statement"},
            {"role": "body", "font_size": 28, "bold": True}],
        "element_schema": [
            {"kind": "shape", "shape_type": "ROUNDED_RECTANGLE (5)"},
            {"kind": "shape", "shape_type": "OVAL (9)"},
            {"kind": "text", "sample": "source document text"}],
    }]}
    result = summarize_template_style(template)
    assert result == {"motifs": ["rounded_cards", "circles"],
                      "title_font_pt": 32, "body_font_pt": 20}
    assert "old factual statement" not in str(result)


def test_template_reference_reads_original_preview_and_rejects_path_escape(tmp_path):
    (tmp_path / "original.png").write_bytes(b"original")
    (tmp_path / "filled.png").write_bytes(b"filled")
    template = {"layout_library": [{"detected_type": "content",
                                    "source_preview": "original.png",
                                    "preview": "filled.png"}]}
    assert read_template_reference(template, tmp_path) == b"original"
    template["layout_library"][0]["source_preview"] = "../escape.png"
    assert read_template_reference(template, tmp_path) == b"filled"
    template["layout_library"][0]["preview"] = "../escape.png"
    assert read_template_reference(template, tmp_path) is None
