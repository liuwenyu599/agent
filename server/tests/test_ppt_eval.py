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


# ---- 预览检查：本地 SQLite 与生产 PostgreSQL 两条后端都要能跑 ----

def _seed_preview_db(tmp_path, layouts, tid="t1"):
    import sqlite3
    db = tmp_path / "judicial_app.db"
    connection = sqlite3.connect(db)
    connection.execute(
        "CREATE TABLE ppt_templates (id TEXT PRIMARY KEY, name TEXT, layout_library TEXT)")
    connection.execute("INSERT INTO ppt_templates VALUES (?, ?, ?)",
                       (tid, "测试模板", json.dumps(layouts, ensure_ascii=False)))
    connection.commit()
    connection.close()
    return db


def _seed_preview_pngs(tmp_path, template_id, layout_ids):
    folder = tmp_path / "ppt" / "tpl_prev" / template_id
    folder.mkdir(parents=True, exist_ok=True)
    for layout_id in layout_ids:
        Image.new("RGB", (8, 8), (255, 255, 255)).save(folder / f"{layout_id}.png")
    return tmp_path / "ppt"


def test_check_previews_sqlite_and_database_url_backends(tmp_path):
    from deploy.ppt_eval.check_previews import check

    layouts = [
        {"id": "L0", "detected_type": "cover", "preview": "L0.png"},
        {"id": "L1", "detected_type": "content", "preview": "L1.png"},
        {"id": "L2", "detected_type": "cards", "preview": "L2.png"},
    ]
    db = _seed_preview_db(tmp_path, layouts)
    ppt_dir = _seed_preview_pngs(tmp_path, "t1", ["L0", "L1", "L2"])
    via_file = check(db, ppt_dir, "t1")
    via_url = check(db, ppt_dir, "t1", database_url=f"sqlite:///{db.as_posix()}")
    assert via_file["backend"] == "sqlite3"
    assert via_url["backend"] == "sqlalchemy"
    assert via_file["ready"] and via_url["ready"]
    assert via_file["content_layouts"] == via_url["content_layouts"] == 2
    assert via_file["vision_reference_ready"] and via_url["vision_reference_ready"]


def test_check_previews_ready_does_not_imply_model_sees_the_image(tmp_path):
    """全是 cards 的模板文件齐、字段齐，但 read_template_reference 仍会退文字摘要。"""
    from deploy.ppt_eval.check_previews import check

    layouts = [{"id": "L1", "detected_type": "cards", "preview": "L1.png"}]
    db = _seed_preview_db(tmp_path, layouts)
    ppt_dir = _seed_preview_pngs(tmp_path, "t1", ["L1"])
    result = check(db, ppt_dir, "t1")
    assert result["ready"] is True
    assert result["vision_reference_ready"] is False


def test_check_previews_flags_missing_png_and_unknown_template(tmp_path):
    import pytest
    from deploy.ppt_eval.check_previews import check

    layouts = [{"id": "L1", "detected_type": "content", "preview": "L1.png"}]
    db = _seed_preview_db(tmp_path, layouts)
    ppt_dir = tmp_path / "ppt"
    ppt_dir.mkdir()
    assert check(db, ppt_dir, "t1")["ready"] is False
    with pytest.raises(ValueError, match="模板不存在"):
        check(db, ppt_dir, "missing")


def test_check_previews_accepts_text_and_parsed_json():
    """SQLite 返回 TEXT，psycopg2 的 json/jsonb 直接返回已解析的 list。"""
    from deploy.ppt_eval.check_previews import _as_layouts

    assert _as_layouts('[{"id": "L1"}]') == [{"id": "L1"}]
    assert _as_layouts([{"id": "L1"}]) == [{"id": "L1"}]
    assert _as_layouts(None) == []
