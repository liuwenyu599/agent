# -*- coding: utf-8 -*-
"""公共图库种子导入回归：幂等、合规校验、坏图不阻断。

幂等键是 name：内容与元数据都没变 → 跳过；图片换了 → 覆盖更新；同名不重复插入。
source / license_note 缺失必须拒绝入库（政务合规），但单条失败不能拖垮整批。
"""
import io
import json
import sys
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.application.ppt import library_seed  # noqa: E402
from app.infrastructure.database.models.ppt import PPTLibraryImageModel  # noqa: E402
from app.infrastructure.database.session import SessionLocal  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_library_table():
    """模块级隔离库会跨用例累积数据，每个用例前清空图库表。"""
    db = SessionLocal()
    try:
        db.query(PPTLibraryImageModel).delete()
        db.commit()
    finally:
        db.close()
    yield


def _make_image(path: Path, size=(640, 480), color=(200, 30, 30), fmt="JPEG"):
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", size, color)
    buffer = io.BytesIO()
    image.save(buffer, format=fmt)
    path.write_bytes(buffer.getvalue())
    return path


def _write_manifest(root: Path, images, defaults=None) -> Path:
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps({
        "version": 1,
        "defaults": defaults if defaults is not None else {
            "source": "本单位自有拍摄",
            "license_note": "内部授权，限本系统 PPT 使用",
        },
        "images": images,
    }, ensure_ascii=False), encoding="utf-8")
    return manifest


def _rows():
    db = SessionLocal()
    try:
        return db.scalars(select(PPTLibraryImageModel)).all()
    finally:
        db.close()


def _run(manifest: Path, ppt_dir: Path, dry_run: bool = False):
    db = SessionLocal()
    try:
        return library_seed.import_library_images(
            db, manifest, base_dir=manifest.parent, ppt_dir=ppt_dir,
            dry_run=dry_run)
    finally:
        db.close()


def test_import_creates_rows_and_thumbnails(tmp_path):
    base = tmp_path / "pack"
    _make_image(base / "法治宣传" / "宪法宣传周.jpg")
    _make_image(base / "党建" / "主题党日.png", fmt="PNG")
    manifest = _write_manifest(base, [
        {"file": "法治宣传/宪法宣传周.jpg", "name": "宪法宣传周",
         "caption": "司法所工作人员向群众发放宪法读本", "category": "法治宣传",
         "tags": ["宪法", "普法"]},
        {"file": "党建/主题党日.png", "name": "主题党日", "category": "党建"},
    ])
    result = _run(manifest, tmp_path / "ppt")
    assert result.created == 2 and not result.errors, result.errors
    rows = {row.name: row for row in _rows()}
    assert set(rows) == {"宪法宣传周", "主题党日"}
    first = rows["宪法宣传周"]
    assert first.tags == ["宪法", "普法"]
    assert first.source == "本单位自有拍摄"
    assert first.license_note.startswith("内部授权")
    assert first.caption.startswith("司法所")
    assert Path(first.file_path).is_file()
    assert Path(first.thumb_path).is_file()
    # 未填 caption 时回落到 name
    assert rows["主题党日"].caption == "主题党日"


def test_reimport_is_idempotent(tmp_path):
    base = tmp_path / "pack"
    _make_image(base / "办公/会议室.jpg")
    manifest = _write_manifest(base, [
        {"file": "办公/会议室.jpg", "name": "会议室", "category": "办公"}])
    first = _run(manifest, tmp_path / "ppt")
    second = _run(manifest, tmp_path / "ppt")
    assert first.created == 1
    assert second.created == 0 and second.updated == 0 and second.skipped == 1
    assert len(_rows()) == 1


def test_changed_metadata_updates_in_place(tmp_path):
    base = tmp_path / "pack"
    _make_image(base / "办公/会议室.jpg")
    manifest = _write_manifest(base, [
        {"file": "办公/会议室.jpg", "name": "会议室", "category": "办公"}])
    _run(manifest, tmp_path / "ppt")
    _write_manifest(base, [
        {"file": "办公/会议室.jpg", "name": "会议室", "category": "会议",
         "caption": "局务会现场", "tags": ["会议"]}])
    result = _run(manifest, tmp_path / "ppt")
    assert result.updated == 1 and result.created == 0
    rows = _rows()
    assert len(rows) == 1
    assert rows[0].category == "会议" and rows[0].tags == ["会议"]


def test_replaced_image_overwrites_file(tmp_path):
    base = tmp_path / "pack"
    path = _make_image(base / "办公/会议室.jpg", color=(10, 120, 40))
    manifest = _write_manifest(base, [
        {"file": "办公/会议室.jpg", "name": "会议室", "category": "办公"}])
    _run(manifest, tmp_path / "ppt")
    original = Path(_rows()[0].file_path).read_bytes()
    _make_image(path, size=(800, 600), color=(10, 10, 200))
    result = _run(manifest, tmp_path / "ppt")
    assert result.updated == 1
    rows = _rows()
    assert len(rows) == 1
    assert rows[0].width == 800
    assert Path(rows[0].file_path).read_bytes() != original


def test_missing_source_or_license_is_rejected(tmp_path):
    base = tmp_path / "pack"
    _make_image(base / "办公/会议室.jpg")
    manifest = _write_manifest(base, [
        {"file": "办公/会议室.jpg", "name": "会议室", "category": "办公"}],
        defaults={})
    result = _run(manifest, tmp_path / "ppt")
    assert result.created == 0
    assert result.errors and "license_note" in result.errors[0] or "source" in result.errors[0]
    assert _rows() == []


def test_bad_entries_do_not_block_batch(tmp_path):
    base = tmp_path / "pack"
    _make_image(base / "办公/会议室.jpg")
    (base / "办公" / "坏图.jpg").write_bytes(b"not an image")
    manifest = _write_manifest(base, [
        {"file": "办公/不存在.jpg", "name": "缺文件", "category": "办公"},
        {"file": "办公/坏图.jpg", "name": "坏图", "category": "办公"},
        {"file": "办公/会议室.jpg", "name": "会议室", "category": "办公"},
    ])
    result = _run(manifest, tmp_path / "ppt")
    assert result.created == 1
    assert len(result.errors) == 2
    assert [row.name for row in _rows()] == ["会议室"]


def test_dry_run_writes_nothing(tmp_path):
    base = tmp_path / "pack"
    _make_image(base / "办公/会议室.jpg")
    manifest = _write_manifest(base, [
        {"file": "办公/会议室.jpg", "name": "会议室", "category": "办公"}])
    ppt = tmp_path / "ppt"
    result = _run(manifest, ppt, dry_run=True)
    assert result.created == 1
    assert _rows() == []
    assert not (ppt / "library").exists()


def test_manifest_without_images_key_is_rejected(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"version": 1}), encoding="utf-8")
    with pytest.raises(library_seed.ManifestError):
        library_seed.load_manifest(manifest)


def test_path_escape_is_rejected(tmp_path):
    base = tmp_path / "pack"
    (base / "office").mkdir(parents=True)
    outside = tmp_path / "outside.jpg"
    _make_image(outside)
    manifest = _write_manifest(base, [
        {"file": "../outside.jpg", "name": "越界图", "category": "办公"}])
    result = _run(manifest, tmp_path / "ppt")
    assert result.created == 0
    assert result.errors and "越出图片包目录" in result.errors[0]
