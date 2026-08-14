# -*- coding: utf-8 -*-
"""写作对话附件服务

职责：把用户上传的材料（Word/PDF/TXT/图片）统一转成"纯文本"，
供 LLMService 注入到对话上下文。

重要说明（模型能力边界）：
- 当前部署的 Qwen2.5-14B-Instruct 是纯文本模型，vLLM 接口不接受图片输入。
- 因此图片附件走 OCR（tesseract）识别为文字后注入；识别质量取决于图片清晰度。
- 若后续部署多模态模型（如 Qwen2.5-VL），只需在 build_attachment_context 之外
  增加"图片直传"分支，本服务的调用方无需改动。
"""
import uuid
from pathlib import Path
from typing import List, Dict, Optional

from sqlalchemy.orm import Session

from backend.config.settings import (
    CHAT_UPLOAD_DIR, CHAT_UPLOAD_MAX_SIZE, CHAT_MAX_ATTACHMENTS,
    CHAT_DOC_TYPES, CHAT_IMAGE_TYPES, ATTACH_CONTEXT_BUDGET,
    OCR_ENABLED, OCR_LANG,
)
from backend.database.models import ChatAttachment


class AttachmentService:
    """对话附件的保存、解析与上下文构建"""

    # ---------- 保存 + 解析 ----------
    async def save_and_parse(self, file, user_id: str, db: Session) -> ChatAttachment:
        filename = file.filename or "unnamed"
        suffix = "." + filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

        if suffix not in CHAT_DOC_TYPES + CHAT_IMAGE_TYPES:
            raise ValueError(f"不支持的文件类型 {suffix or '(无扩展名)'}，"
                             f"支持：{'、'.join(CHAT_DOC_TYPES + CHAT_IMAGE_TYPES)}")

        data = await file.read()
        if len(data) > CHAT_UPLOAD_MAX_SIZE:
            raise ValueError(f"文件超过大小限制（{CHAT_UPLOAD_MAX_SIZE // 1024 // 1024}MB）")

        att_id = str(uuid.uuid4())
        kind = "image" if suffix in CHAT_IMAGE_TYPES else "doc"

        user_dir = CHAT_UPLOAD_DIR / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        file_path = user_dir / f"{att_id}{suffix}"
        file_path.write_bytes(data)

        text, status, note = self._extract(file_path, suffix, kind)

        att = ChatAttachment(
            id=att_id,
            user_id=user_id,
            filename=filename,
            kind=kind,
            file_path=str(file_path),
            file_size=len(data),
            text_content=text,
            parse_status=status,
            parse_note=note,
        )
        db.add(att)
        db.commit()
        db.refresh(att)
        return att

    # ---------- 解析 ----------
    def _extract(self, file_path: Path, suffix: str, kind: str):
        """返回 (text, status, note)"""
        if kind == "image":
            return self._ocr_image(file_path)

        # 文档类：复用知识库的解析逻辑，保持行为一致
        try:
            from backend.services.document_service import DocumentService
            text = DocumentService(embedder=None)._extract_text(file_path, file_path.name)
        except Exception as e:
            return "", "failed", f"解析失败: {e}"

        if not text or not text.strip():
            return "", "failed", "未能从文件中提取到文字内容"
        # 截断过长的提取结果，防止数据库膨胀
        if len(text) > 100000:
            return text[:100000], "partial", "内容过长，仅保留前 10 万字符"
        if text.startswith("[") and "失败" in text:
            return text, "failed", text
        return text, "ok", ""

    def _ocr_image(self, file_path: Path):
        if not OCR_ENABLED:
            return "", "failed", "OCR 未启用（OCR_ENABLED=false）"
        try:
            import pytesseract
            from PIL import Image
            text = pytesseract.image_to_string(Image.open(str(file_path)), lang=OCR_LANG)
            text = text.strip()
            if not text:
                return "", "partial", "OCR 未识别到文字（可能是清晰度不足或非文字图片）"
            return text, "ok", "图片内容经 OCR 识别"
        except ImportError:
            return "", "failed", "服务器未安装 pytesseract/Pillow，无法识别图片"
        except Exception as e:
            return "", "failed", f"OCR 识别失败: {e}（请确认已安装 tesseract-ocr 及中文语言包 chi_sim）"

    # ---------- 上下文构建 ----------
    def bind_to_session(self, attachment_ids: List[str], session_id: str,
                        user_id: str, db: Session):
        """把附件绑定到会话（上传时可能还没有 session_id）"""
        db.query(ChatAttachment).filter(
            ChatAttachment.id.in_(attachment_ids),
            ChatAttachment.user_id == user_id,
        ).update({"session_id": session_id}, synchronize_session=False)
        db.commit()

    def get_attachments(self, attachment_ids: List[str], user_id: str,
                        db: Session) -> List[ChatAttachment]:
        return db.query(ChatAttachment).filter(
            ChatAttachment.id.in_(attachment_ids),
            ChatAttachment.user_id == user_id,
        ).all()

    def get_session_attachments(self, session_id: str, db: Session) -> List[ChatAttachment]:
        return db.query(ChatAttachment).filter(
            ChatAttachment.session_id == session_id
        ).order_by(ChatAttachment.created_at).all()

    def build_attachment_context(self, attachments: List[ChatAttachment],
                                 budget: int = ATTACH_CONTEXT_BUDGET) -> str:
        """把附件文本拼接为注入模型的上下文块，带总预算截断。

        策略：按附件顺序平均分配预算，每个附件至少 300 字；
        超长附件保留开头（公文关键信息通常在开头：标题、主送、背景）。
        """
        usable = [a for a in attachments if a.text_content and a.parse_status in ("ok", "partial")]
        if not usable:
            return ""
        per = max(300, budget // len(usable))
        blocks = []
        for a in usable:
            text = a.text_content[:per]
            truncated = "（内容过长已截断）" if len(a.text_content) > per else ""
            note = "（图片经 OCR 识别）" if a.kind == "image" else ""
            blocks.append(f"【附件材料：{a.filename}】{note}\n{text}{truncated}")
        return "\n\n".join(blocks)

    def summarize_for_message(self, attachments: List[ChatAttachment]) -> List[Dict]:
        """存到消息里的附件摘要"""
        return [{
            "id": a.id, "filename": a.filename, "kind": a.kind,
            "parse_status": a.parse_status, "parse_note": a.parse_note,
        } for a in attachments]
