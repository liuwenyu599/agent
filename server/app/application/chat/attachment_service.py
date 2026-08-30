"""写作对话附件服务（移植自旧 services/attachment_service.py）。

把用户上传的材料（Word/PDF/TXT/图片）统一转成纯文本注入模型上下文。
- 图片走 OCR（tesseract）；PDF 走专用解析器（正文+链接+表格+扫描件 OCR 回退）；
- build_attachment_context 支持按用户当前问题做页级相关度选择，带总预算控制。

references 模块复用本类的 extract() 做同样的文件解析。
"""
import re
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.domain.chat.entities import ChatAttachment
from app.infrastructure.repositories.chat import SqlAlchemyChatAttachmentRepository

logger = get_logger(__name__)

_PAGE_MARK_RE = re.compile(r"【第\d+页】")
_FALLBACK_BLOCK_CHARS = 800
_HEAD_CHARS = 300
TEXT_MAX_CHARS = 100000  # 与旧系统一致


class AttachmentService:
    """对话附件的保存、解析与上下文构建。"""

    def __init__(self, db: Session = None) -> None:
        self.db = db

    # ---------- 保存 + 解析 ----------
    async def save_and_parse(self, file, user_id: str, db: Session = None) -> ChatAttachment:
        db = db or self.db
        filename = file.filename or "unnamed"
        suffix = "." + filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

        if suffix not in settings.CHAT_SUPPORTED_TYPES:
            raise ValueError(f"不支持的文件类型 {suffix or '(无扩展名)'}，"
                             f"支持：{'、'.join(settings.CHAT_SUPPORTED_TYPES)}")

        data = await file.read()
        if len(data) > settings.UPLOAD_MAX_SIZE:
            raise ValueError(f"文件超过大小限制（{settings.UPLOAD_MAX_SIZE // 1024 // 1024}MB）")

        att_id = str(uuid.uuid4())
        kind = "image" if suffix in settings.CHAT_IMAGE_TYPES else "doc"

        user_dir = settings.uploads_dir / "chat" / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        file_path = user_dir / f"{att_id}{suffix}"
        file_path.write_bytes(data)

        text, status, note = self.extract(file_path, suffix, kind)

        att = ChatAttachment(
            id=att_id, user_id=user_id, filename=filename, kind=kind,
            file_path=str(file_path), file_size=len(data),
            text_content=text, parse_status=status, parse_note=note,
        )
        return SqlAlchemyChatAttachmentRepository(db).add(att)

    # ---------- 解析 ----------
    def extract(self, file_path: Path, suffix: str, kind: str):
        """返回 (text, status, note)。references 模块复用。"""
        if kind == "image":
            return self._ocr_image(file_path)

        if suffix == ".pdf":
            return self._extract_pdf(file_path)

        # 其他文档类：复用知识库的解析逻辑，保持行为一致
        try:
            from app.application.knowledge.document_service import DocumentService
            text = DocumentService().extract_text(file_path, file_path.name)
        except Exception as e:
            return "", "failed", f"解析失败: {e}"

        if not text or not text.strip():
            return "", "failed", "未能从文件中提取到文字内容"
        if len(text) > TEXT_MAX_CHARS:
            return text[:TEXT_MAX_CHARS], "partial", "内容过长，仅保留前 10 万字符"
        if text.startswith("[") and "失败" in text:
            return text, "failed", text
        return text, "ok", ""

    # 兼容旧命名（旧代码调用 _extract）
    _extract = extract

    def _extract_pdf(self, file_path: Path):
        from app.application.chat.pdf_parser import extract_pdf
        try:
            result = extract_pdf(file_path)
        except Exception as e:
            return "", "failed", f"PDF 解析失败: {e}"

        text = (result.get("text") or "").strip()
        if not text:
            if result.get("is_scanned"):
                return "", "failed", "该 PDF 为扫描件且 OCR 未成功识别，请确认已安装 tesseract 中文语言包"
            return "", "failed", "未能从 PDF 中提取到文字内容"

        parts = [text]
        notes = []
        if result.get("is_scanned"):
            notes.append("扫描件")
        if result.get("ocr_used"):
            notes.append("经 OCR 识别")

        links = result.get("links") or []
        if links:
            lines = []
            for i, lk in enumerate(links[:100]):
                page = f"（第{lk['page']}页）" if lk.get("page") else ""
                lines.append(f"{i + 1}. {lk['url']}{page}")
            parts.append("【文档中的链接】\n" + "\n".join(lines))
            notes.append(f"含 {len(links)} 个链接")

        tables = result.get("tables") or []
        if tables:
            tlines = []
            for t in tables[:20]:
                tlines.append(f"（第{t['page']}页表格）")
                for row in t["rows"]:
                    tlines.append(" | ".join(row))
            parts.append("【文档中的表格】\n" + "\n".join(tlines))
            notes.append(f"含 {len(tables)} 个表格")

        full = "\n\n".join(parts)
        if len(full) > TEXT_MAX_CHARS:
            return full[:TEXT_MAX_CHARS], "partial", "内容过长，仅保留前 10 万字符" + ("；" + "，".join(notes) if notes else "")
        return full, "ok", "，".join(notes)

    def _ocr_image(self, file_path: Path):
        if not settings.OCR_ENABLED:
            return "", "failed", "OCR 未启用（OCR_ENABLED=false）"
        try:
            import pytesseract
            from PIL import Image
            text = pytesseract.image_to_string(
                Image.open(str(file_path)), lang=settings.OCR_LANG
            ).strip()
            if not text:
                return "", "partial", "OCR 未识别到文字（可能是清晰度不足或非文字图片）"
            return text, "ok", "图片内容经 OCR 识别"
        except ImportError:
            return "", "failed", "服务器未安装 pytesseract/Pillow，无法识别图片"
        except Exception as e:
            return "", "failed", f"OCR 识别失败: {e}（请确认已安装 tesseract-ocr 及中文语言包 chi_sim）"

    # ---------- 上下文构建 ----------
    def bind_to_session(self, attachment_ids: List[str], session_id: str,
                        user_id: str, db: Session = None):
        SqlAlchemyChatAttachmentRepository(db or self.db).bind_to_session(
            attachment_ids, session_id, user_id
        )

    def get_attachments(self, attachment_ids: List[str], user_id: str,
                        db: Session = None) -> List[ChatAttachment]:
        return SqlAlchemyChatAttachmentRepository(db or self.db).list_by_ids_for_user(
            attachment_ids, user_id
        )

    def get_session_attachments(self, session_id: str, db: Session = None) -> List[ChatAttachment]:
        return SqlAlchemyChatAttachmentRepository(db or self.db).list_by_session(session_id)

    # ---------- 预算内相关度选择 ----------
    @staticmethod
    def _split_blocks(text: str) -> List[str]:
        if _PAGE_MARK_RE.search(text):
            parts = _PAGE_MARK_RE.split(text)
            marks = _PAGE_MARK_RE.findall(text)
            blocks = []
            if parts and parts[0].strip():
                blocks.append(parts[0].strip())
            for mark, body in zip(marks, parts[1:]):
                block = (mark + "\n" + body).strip()
                if block:
                    blocks.append(block)
            return blocks
        return [text[i:i + _FALLBACK_BLOCK_CHARS]
                for i in range(0, len(text), _FALLBACK_BLOCK_CHARS)]

    @staticmethod
    def _query_terms(query: str) -> List[str]:
        terms = re.findall(r"[一-龥]{2,}|[A-Za-z0-9]{2,}", query or "")
        stop = {"可以", "一下", "帮我", "什么", "怎么", "哪些", "这个", "那个",
                "里面", "请", "的", "了", "吗", "吧", "呢"}
        return [t for t in terms if t not in stop]

    def _select_within_budget(self, text: str, query: Optional[str], budget: int) -> str:
        """单个附件在预算内：开头 + 链接段始终保留；其余按相关度选块，保持页序。"""
        if len(text) <= budget:
            return text

        special = ""
        body_text = text
        for m in re.finditer(r"【文档中的(?:链接|表格)】[\s\S]*?(?=\n\n【(?!文档中的)|$)", text):
            special += m.group(0).strip() + "\n\n"
            body_text = body_text.replace(m.group(0), "")

        head = body_text[:_HEAD_CHARS]
        rest = body_text[_HEAD_CHARS:]
        blocks = self._split_blocks(rest)

        remaining = budget - len(head) - len(special) - 20
        if remaining <= 0:
            return (head + "\n...\n" + special).strip()

        terms = self._query_terms(query)
        if terms:
            scored = sorted(range(len(blocks)),
                            key=lambda i: sum(blocks[i].count(t) for t in terms),
                            reverse=True)
        else:
            scored = list(range(len(blocks)))

        chosen_idx = []
        used = 0
        for i in scored:
            blen = len(blocks[i]) + 2
            if used + blen > remaining:
                continue
            chosen_idx.append(i)
            used += blen

        chosen = [blocks[i] for i in sorted(chosen_idx)]
        body = "\n\n".join(chosen)
        omitted = len(blocks) - len(chosen)
        tail = f"\n（另有 {omitted} 个片段因长度限制未注入，可针对具体内容继续提问）" if omitted > 0 else ""
        return (head + "\n...\n" + body + tail + ("\n\n" + special if special else "")).strip()

    def build_attachment_context(self, attachments: List[ChatAttachment],
                                 budget: int = None,
                                 query: Optional[str] = None) -> str:
        budget = budget or settings.ATTACH_CONTEXT_BUDGET
        usable = [a for a in attachments
                  if a.text_content and a.parse_status in ("ok", "partial")]
        if not usable:
            return ""
        per = max(300, budget // len(usable))
        blocks = []
        for a in usable:
            text = self._select_within_budget(a.text_content, query, per)
            truncated = "（内容经相关度筛选）" if len(a.text_content) > per else ""
            note = "（图片经 OCR 识别）" if a.kind == "image" else ""
            if a.parse_note:
                note = f"{note}（{a.parse_note}）" if note else f"（{a.parse_note}）"
            blocks.append(f"【附件材料：{a.filename}】{note}\n{text}{truncated}")
        return "\n\n".join(blocks)

    def summarize_for_message(self, attachments: List[ChatAttachment]) -> List[Dict]:
        return [{
            "id": a.id, "filename": a.filename, "kind": a.kind,
            "parse_status": a.parse_status, "parse_note": a.parse_note,
        } for a in attachments]
