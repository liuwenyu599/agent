import json
import sys
import io
from pathlib import Path

from PIL import Image
from pptx import Presentation
from app.application.ppt import ppt_engine


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from deploy.ppt_eval.score import measure, summarize_ratings  # noqa: E402


def test_fixed_ten_page_material_and_metrics(tmp_path):
    outline = json.loads((ROOT / "deploy/ppt_eval/fixed_10p.json").read_text(
        encoding="utf-8"))
    assert len(outline["slides"]) == 10
    assert outline["slides"][3]["blocks"]["chart"]["series"][0]["values"] == [35, 17, 23, 11]
    deck = ppt_engine.render_pptx(
        ppt_engine.normalize_outline(outline, require_bookends=False),
        ppt_engine.template_to_dict(ppt_engine.builtin_template("public_service_green")),
        adaptive=True)
    output = tmp_path / "blind-a.pptx"
    output.write_bytes(deck)
    report = measure(output)
    assert len(report["pages"]) == 10
    assert report["deck_metrics"]["visual_elements_per_page"] >= 0
    assert "human_ratings" not in report
    # The full-slide transparent SVG visual layer is not a real evidence photo.
    prs = Presentation(str(output))
    payload = io.BytesIO()
    Image.new("RGB", (120, 80), "white").save(payload, format="PNG")
    photo = prs.slides[3].shapes.add_picture(
        io.BytesIO(payload.getvalue()), 0, 0,
        int(prs.slide_width * .40), int(prs.slide_height * .40))
    photo.name = "PPTEvidencePhoto"
    decoration = prs.slides[3].shapes.add_picture(
        io.BytesIO(payload.getvalue()), 0, 0,
        prs.slide_width, prs.slide_height)
    decoration.name = "PPTVisualLayer"
    prs.save(str(output))
    measured = measure(output)
    assert measured["deck_metrics"]["photo_pages"] == 1
    assert measured["pages"][3]["photo_area_fraction"] == .16


def test_blind_scores_require_two_judges_and_photo_relevance():
    pages = [{"page": i, "has_photo": i == 4} for i in range(1, 11)]
    rows = [{"clarity": 4, "hierarchy": 4, "visual_fit": 4,
             "factual_fidelity": 5, "rhythm": 3,
             "image_relevance": 5 if i == 4 else None}
            for i in range(1, 11)]
    summary = summarize_ratings({"judges": [{"pages": rows}, {"pages": rows}]}, pages)
    assert summary["image_relevance"] == 5
    assert summary["judges"] == 2
