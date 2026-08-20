# -*- coding: utf-8 -*-
"""写作对话附件服务

职责：把用户上传的材料（Word/PDF/TXT/图片）统一转成"纯文本"，
供 LLMService 注入到对话上下文。

重要说明（模型能力边界）：
- 当前部署的 Qwen2.5-14B-Instruct 是纯文本模型，vLLM 接口不接受图片输入。
- 因此图片附件走 OCR（tesseract）识别为文字后注入；识别质量取决于图片清晰度。
- 若后续部署多模态模型（如 Qwen2.5-VL），只需在 build_attachment_context 之外
  增加"图片直传"分支，本服务的调用方无需改动。

PDF 专项（2026-08 修复）：
- PDF 不再走 PyPDF2 纯文字提取，改走 rag/parser/pdf_parser.extract_pdf：
  逐页正文（带【第N页】标记）+ URI 超链接注释 + 正文裸 URL + 表格 + 扫描件 OCR 回退；
- 链接清单单独拼入 text_content 尾部，保证 AI 一定能"看到" URL；
- build_attachment_context 支持按用户当前问题做页级相关度选择，
  大 PDF 不再只截断前 N 字，而是"链接清单 + 开头 + 相关页"。
"""
import re
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

# 页标记（pdf_parser 输出）与兜底分块大小
_PAGE_MARK_RE = re.compile(r"【第\d+页】")
_FALLBACK_BLOCK_CHARS = 800
# 每个附件上下文最少保留的开头字数（公文关键信息通常在开头）
_HEAD_CHARS = 300


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

        # PDF：走专用解析器（正文 + 链接 + 表格 + 扫描件 OCR）
        if suffix == ".pdf":
            return self._extract_pdf(file_path)

        # 其他文档类：复用知识库的解析逻辑，保持行为一致
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

    def _extract_pdf(self, file_path: Path):
        """PDF 解析：正文 + 链接清单 + 表格，扫描件自动 OCR 回退"""
        try:
            from backend.rag.parser.pdf_parser import extract_pdf
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

        # 链接清单：单独成段，确保不被正文淹没
        links = result.get("links") or []
        if links:
            lines = []
            for i, lk in enumerate(links[:100]):  # 最多保留 100 条
                page = f"（第{lk['page']}页）" if lk.get("page") else ""
                lines.append(f"{i + 1}. {lk['url']}{page}")
            parts.append("【文档中的链接】\n" + "\n".join(lines))
            notes.append(f"含 {len(links)} 个链接")

        # 表格：转为文本行
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
        if len(full) > 100000:
            return full[:100000], "partial", "内容过长，仅保留前 10 万字符" + ("；" + "，".join(notes) if notes else "")
        return full, "ok", "，".join(notes)

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

    # ---------- 预算内相关度选择 ----------
    @staticmethod
    def _split_blocks(text: str) -> List[str]:
        """按【第N页】标记分块；无页标记时按固定字符数兜底分块。"""
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
        """从用户问题中提取用于相关度匹配的词（二字及以上连续中文/英文数字串）"""
        terms = re.findall(r"[一-龥]{2,}|[A-Za-z0-9]{2,}", query or "")
        stop = {"可以", "一下", "帮我", "帮我", "什么", "怎么", "哪些", "这个", "那个",
                "里面", "一下", "请", "的", "了", "吗", "吧", "呢"}
        return [t for t in terms if t not in stop]

    def _select_within_budget(self, text: str, query: Optional[str],
                              budget: int) -> str:
        """单个附件在预算内的内容选择：
        开头(_HEAD_CHARS) + 链接段 始终保留；其余按与 query 的相关度选块，保持原始页序。
        """
        if len(text) <= budget:
            return text

        # 链接段/表格段单独抽出，优先保留（信息密度高、长度小），并从正文中移除避免重复
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
            scored = sorted(
                range(len(blocks)),
                key=lambda i: sum(blocks[i].count(t) for t in terms),
                reverse=True,
            )
        else:
            scored = list(range(len(blocks)))  # 无 query 时按顺序取

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
                                 budget: int = ATTACH_CONTEXT_BUDGET,
                                 query: Optional[str] = None) -> str:
        """把附件文本拼接为注入模型的上下文块，带总预算控制。

        策略：
        - 按附件数平均分配预算，每个附件至少 300 字；
        - 短附件全量注入；
        - 长附件：开头 + 链接清单 必保留，其余按与用户当前问题的相关度
          做页级选择（大 PDF 不再只截前 N 字）。
        """
        usable = [a for a in attachments if a.text_content and a.parse_status in ("ok", "partial")]
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
        """存到消息里的附件摘要"""
        return [{
            "id": a.id, "filename": a.filename, "kind": a.kind,
            "parse_status": a.parse_status, "parse_note": a.parse_note,
        } for a in attachments]