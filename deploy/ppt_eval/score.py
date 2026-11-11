"""Extract reproducible PPTX measures for the fixed ten-page blind evaluation."""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE


DIMENSIONS = ("clarity", "hierarchy", "visual_fit", "factual_fidelity", "rhythm")


def measure(path: Path, ratings: dict | None = None) -> dict:
    deck = Presentation(str(path))
    if len(deck.slides) != 10:
        raise ValueError(f"评测集要求 10 页，实际为 {len(deck.slides)} 页")
    page_area = deck.slide_width * deck.slide_height
    pages = []
    for number, slide in enumerate(deck.slides, 1):
        visual_count = 0
        photo_area = text_area = 0.0
        sizes = []
        for shape in slide.shapes:
            area = max(0, shape.width * shape.height) / page_area
            is_picture = shape.shape_type == MSO_SHAPE_TYPE.PICTURE
            is_photo = is_picture and shape.name.startswith("PPTEvidencePhoto")
            has_chart = bool(getattr(shape, "has_chart", False))
            if is_photo:
                photo_area += min(area, 1.0)
            if shape.has_text_frame and shape.text.strip():
                text_area += min(area, 1.0)
                for paragraph in shape.text_frame.paragraphs:
                    for run in paragraph.runs:
                        if run.text.strip() and run.font.size is not None:
                            sizes.append(round(run.font.size.pt, 2))
            elif (is_picture or has_chart or
                  (shape.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE and area < .90)):
                visual_count += 1
        ratio = photo_area / (photo_area + text_area) if photo_area + text_area else 0.0
        pages.append({"page": number, "visual_elements": visual_count,
                      "font_size_std_pt": round(statistics.pstdev(sizes), 2) if sizes else None,
                      "photo_area_fraction": round(photo_area, 3),
                      "text_area_fraction": round(text_area, 3),
                      "image_text_ratio": round(ratio, 3),
                      "has_photo": photo_area > 0})
    ratios = [page["image_text_ratio"] for page in pages]
    font_spreads = [page["font_size_std_pt"] for page in pages
                    if page["font_size_std_pt"] is not None]
    result = {"benchmark_id": "judicial-discipline-10p-v1",
              "pages": pages,
              "deck_metrics": {
                  "visual_elements_per_page": round(statistics.mean(
                      page["visual_elements"] for page in pages), 2),
                  "font_size_std_pt_mean": round(statistics.mean(font_spreads), 2)
                  if font_spreads else None,
                  "image_text_ratio_volatility": round(statistics.pstdev(ratios), 3),
                  "photo_pages": sum(page["has_photo"] for page in pages)}}
    if ratings is not None:
        result["human_ratings"] = summarize_ratings(ratings, pages)
    return result


def summarize_ratings(ratings: dict, pages: list[dict]) -> dict:
    judges = ratings.get("judges") or []
    if len(judges) < 2:
        raise ValueError("盲评至少需要两名独立评审")
    scores = {dimension: [] for dimension in DIMENSIONS}
    relevance = []
    for judge in judges:
        rows = judge.get("pages") or []
        if len(rows) != 10:
            raise ValueError("每位评审须对 10 页逐页评分")
        for page, row in zip(pages, rows):
            for dimension in DIMENSIONS:
                value = row.get(dimension)
                if type(value) not in (int, float) or not 1 <= value <= 5:
                    raise ValueError(f"第 {page['page']} 页 {dimension} 须为 1–5 分")
                scores[dimension].append(value)
            image_score = row.get("image_relevance")
            if page["has_photo"]:
                if type(image_score) not in (int, float) or not 1 <= image_score <= 5:
                    raise ValueError(f"第 {page['page']} 页有照片，须评图片与内容相关性")
                relevance.append(image_score)
            elif image_score is not None:
                raise ValueError(f"第 {page['page']} 页无照片，image_relevance 须为 null")
    return {**{key: round(statistics.mean(values), 2) for key, values in scores.items()},
            "image_relevance": round(statistics.mean(relevance), 2) if relevance else None,
            "judges": len(judges)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pptx", type=Path)
    parser.add_argument("--ratings", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    rating_data = json.loads(args.ratings.read_text(encoding="utf-8")) if args.ratings else None
    report = measure(args.pptx, rating_data)
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(output + "\n", encoding="utf-8")
    else:
        print(output)
