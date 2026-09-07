"""文档版本管理服务。

安全约束：所有查询强制按 user_id 过滤，用户之间互相看不到文档。
"""
from datetime import datetime
from typing import List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.infrastructure.database.models.document import (
    MyDocumentModel,
    MyDocumentVersionModel,
)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


class DocumentService:
    def __init__(self, db: Session):
        self.db = db

    # ---------- 查询 ----------

    def _get_owned(self, doc_id: str, user_id: str) -> MyDocumentModel:
        doc = self.db.get(MyDocumentModel, doc_id)
        if not doc or doc.user_id != user_id:
            # 不区分"不存在"与"无权访问"，避免泄露他人文档存在性
            raise HTTPException(status_code=404, detail="文档不存在")
        return doc

    def list_documents(self, user_id: str) -> List[dict]:
        rows = self.db.scalars(
            select(MyDocumentModel)
            .where(MyDocumentModel.user_id == user_id)
            .order_by(desc(MyDocumentModel.updated_at))
        ).all()
        return [self._summary(d) for d in rows]

    def get_document(self, doc_id: str, user_id: str) -> dict:
        doc = self._get_owned(doc_id, user_id)
        latest = self._latest_version(doc)
        return {
            **self._summary(doc),
            "content": latest.content if latest else "",
            "quality": latest.quality if latest else None,
            "content_check": latest.content_check if latest else None,
            "versions": [self._version_item(v) for v in doc.versions],
        }

    def get_version(self, doc_id: str, version_no: int, user_id: str) -> dict:
        doc = self._get_owned(doc_id, user_id)
        v = self.db.scalar(
            select(MyDocumentVersionModel).where(
                MyDocumentVersionModel.document_id == doc.id,
                MyDocumentVersionModel.version_no == version_no,
            )
        )
        if not v:
            raise HTTPException(status_code=404, detail="版本不存在")
        return {
            **self._version_item(v),
            "document_id": doc.id,
            "title": doc.title,
            "content": v.content,
            "quality": v.quality,
            "content_check": v.content_check,
        }

    # ---------- 写入 ----------

    def create_document(self, user_id: str, req) -> dict:
        doc = MyDocumentModel(
            user_id=user_id,
            title=req.title or "未命名文档",
            doc_type=req.doc_type,
            document_number=req.document_number,
            document_date=req.document_date,
            session_id=req.session_id,
            current_version=1,
            status="draft",
        )
        self.db.add(doc)
        self.db.flush()
        self.db.add(MyDocumentVersionModel(
            document_id=doc.id, version_no=1, content=req.content,
            quality=req.quality, content_check=req.content_check,
            note=req.note or "初始版本", created_by=user_id,
        ))
        self.db.commit()
        self.db.refresh(doc)
        return self.get_document(doc.id, user_id)

    def save_version(self, doc_id: str, user_id: str, req) -> dict:
        doc = self._get_owned(doc_id, user_id)
        new_no = (doc.current_version or 0) + 1
        latest = self._latest_version(doc)
        self.db.add(MyDocumentVersionModel(
            document_id=doc.id, version_no=new_no, content=req.content,
            quality=latest.quality if latest else None,
            content_check=latest.content_check if latest else None,
            note=req.note or f"版本 {new_no}", created_by=user_id,
        ))
        doc.current_version = new_no
        if req.title:
            doc.title = req.title
        if req.status:
            doc.status = req.status
        doc.updated_at = datetime.utcnow()
        self.db.commit()
        return self.get_document(doc.id, user_id)

    def delete_document(self, doc_id: str, user_id: str) -> None:
        doc = self._get_owned(doc_id, user_id)
        self.db.delete(doc)
        self.db.commit()

    # ---------- 内部 ----------

    def _latest_version(self, doc: MyDocumentModel) -> Optional[MyDocumentVersionModel]:
        return self.db.scalar(
            select(MyDocumentVersionModel)
            .where(MyDocumentVersionModel.document_id == doc.id)
            .order_by(desc(MyDocumentVersionModel.version_no))
            .limit(1)
        )

    @staticmethod
    def _summary(d: MyDocumentModel) -> dict:
        return {
            "id": d.id, "title": d.title, "doc_type": d.doc_type,
            "document_number": d.document_number,
            "document_date": d.document_date,
            "current_version": d.current_version, "status": d.status,
            "created_at": _iso(d.created_at), "updated_at": _iso(d.updated_at),
        }

    @staticmethod
    def _version_item(v: MyDocumentVersionModel) -> dict:
        return {
            "version_no": v.version_no, "note": v.note,
            "created_by": v.created_by, "created_at": _iso(v.created_at),
            "char_count": len(v.content or ""),
        }
