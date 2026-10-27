from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.writing import ProductionWritingTaskService
from app.application.writing.eval_capture_service import EvalCaptureWritingTaskService
from app.application.writing.task_service import WritingTaskService
from app.infrastructure.database.base import Base
from app.infrastructure.database.models.document import MyDocumentModel, MyDocumentVersionModel
from app.infrastructure.database.models.identity import UserModel  # noqa: F401 - registers FK target
from app.infrastructure.database.models.training import TrainingSampleModel
from app.infrastructure.database.models.writing_task import WritingTaskModel


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _task_with_version(db, *, note="V1 AI 初稿", content="AI版本正文。", ai_draft="最早AI初稿。"):
    doc = MyDocumentModel(
        user_id="u1",
        title="测试通知",
        doc_type="通知",
        current_version=1,
        status="draft",
    )
    db.add(doc)
    db.flush()
    db.add(MyDocumentVersionModel(
        document_id=doc.id,
        version_no=1,
        content=content,
        note=note,
        created_by="u1",
    ))
    task = WritingTaskModel(
        user_id="u1",
        document_id=doc.id,
        context={"title": "测试通知", "document_type": "通知"},
        current_content=content,
        ai_draft=ai_draft,
        version_no=1,
        status="editing",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def test_public_service_keeps_eval_capture_in_production_chain():
    assert issubclass(ProductionWritingTaskService, EvalCaptureWritingTaskService)
    assert not issubclass(WritingTaskService, EvalCaptureWritingTaskService)


def test_ai_version_note_classifier_excludes_manual_and_structural_versions():
    check = EvalCaptureWritingTaskService._is_ai_version_note
    assert check("V1 AI 初稿")
    assert check("V2 继续生成")
    assert check("AI 修改：润色全文")
    assert check("AI 局部修改：精简第二段")
    assert not check("人工编辑")
    assert not check("结构字段同步")
    assert not check(None)


def test_manual_save_after_ai_version_captures_latest_ai_to_final_pair():
    db = _db()
    try:
        latest_ai = "这是最近一次AI修改后的正文，而不是最早初稿。"
        task = _task_with_version(db, content=latest_ai, ai_draft="这是最早AI初稿。")
        service = EvalCaptureWritingTaskService(db)

        final = "这是用户在最近AI版本基础上人工修改后的最终正文。"
        result = service.save_version(task.id, "u1", final, note="人工编辑")

        assert result["version_no"] == 2
        assert result["eval_captured"] is True
        assert result["eval_source_version"] == 1
        assert result["eval_final_version"] == 2
        assert result["eval_diff"]["similarity"] < 1.0

        samples = db.query(TrainingSampleModel).all()
        assert len(samples) == 1
        sample = samples[0]
        assert sample.draft == latest_ai
        assert sample.draft != task.ai_draft
        assert sample.output == final
        assert sample.source == "writing_eval"
        assert sample.status == "candidate"
        assert sample.biz_type == "通知"
    finally:
        db.close()


def test_manual_after_manual_does_not_duplicate_eval_sample():
    db = _db()
    try:
        task = _task_with_version(db, content="AI正文版本。")
        service = EvalCaptureWritingTaskService(db)

        first = service.save_version(task.id, "u1", "第一次人工编辑。", note="人工编辑")
        second = service.save_version(task.id, "u1", "第二次人工编辑。", note="继续人工编辑")

        assert first["eval_captured"] is True
        assert second["eval_captured"] is False
        assert db.query(TrainingSampleModel).count() == 1
    finally:
        db.close()


def test_unchanged_manual_save_after_ai_does_not_create_low_value_pair():
    db = _db()
    try:
        text = "AI正文完全未改。"
        task = _task_with_version(db, content=text)
        result = EvalCaptureWritingTaskService(db).save_version(
            task.id, "u1", text, note="仅点击保存")

        assert result["eval_captured"] is False
        assert db.query(TrainingSampleModel).count() == 0
    finally:
        db.close()


def test_historical_ai_export_captures_the_exported_version_not_current_text():
    db = _db()
    try:
        task = _task_with_version(db, content="AI v1 正文。")
        task.current_content = "随后另行编辑的正文。"
        db.commit()

        EvalCaptureWritingTaskService(db)._try_capture_accepted(task.id, "u1", version_no=1)

        sample = db.query(TrainingSampleModel).one()
        assert sample.draft == "AI v1 正文。"
        assert sample.output == "AI v1 正文。"
    finally:
        db.close()
