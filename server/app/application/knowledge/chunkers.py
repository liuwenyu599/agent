"""文档分块器（v2：结构识别 + 尺寸约束 + 重叠 + 文档标题面包屑）。

策略：
1. 先按公文结构（一、（一）1.（1））或法规结构（第x条）切出逻辑段；
2. 逻辑段超过 RAG_CHUNK_MAX_CHARS 时按句子边界再切，块间保留 RAG_CHUNK_OVERLAP 重叠；
3. 过短碎块（< RAG_CHUNK_MIN_CHARS）并入前一块，避免低信息量向量稀释召回；
4. 每块内容前置「《文档标题》」面包屑——向量与关键词检索都带上文档身份，
   检索历史公文时可区分不同文件里雷同的章节（如各文都有的"工作要求"）。
"""
import re
from typing import Dict, List, Tuple

from app.core.config import settings

# 中文句子边界：句号/叹号/问号/分号之后
_SENT_RE = re.compile(r"(?<=[。！？；])")


class _BaseChunker:
    """结构分段 + 尺寸约束 + 重叠 + 合并碎块的通用流程。子类只定义结构正则。"""

    SECTION_RE: str = ""
    chunk_type: str = "section"
    min_section_chars: int = 20

    def __init__(self) -> None:
        self.max_chars = settings.RAG_CHUNK_MAX_CHARS
        self.overlap = settings.RAG_CHUNK_OVERLAP
        self.min_chars = settings.RAG_CHUNK_MIN_CHARS

    # ---- 对外入口 ----

    def chunk(self, text: str, doc_id: str, title: str = "") -> List[Dict]:
        sections = self._split_sections(text)
        raw: List[Tuple[str, str]] = []
        for heading, body in sections:
            piece_text = f"{heading} {body}".strip() if heading else body.strip()
            for piece in self._fit_size(piece_text):
                raw.append((heading, piece))
        merged = self._merge_small(raw)
        return [
            self._record(i, heading, piece, title)
            for i, (heading, piece) in enumerate(merged)
        ]

    # ---- 结构分段 ----

    def _split_sections(self, text: str) -> List[Tuple[str, str]]:
        matches = re.findall(self.SECTION_RE, text, re.DOTALL) if self.SECTION_RE else []
        sections = [
            (m[0].strip(), m[1].strip())
            for m in matches
            if len(m[1].strip()) > self.min_section_chars
        ]
        if sections:
            return sections
        # 无结构（纯叙述文）：按空行段落切
        return [
            ("", p.strip())
            for p in re.split(r"\n\s*\n", text)
            if p.strip()
        ]

    # ---- 尺寸约束：句子边界切分 + 重叠 ----

    def _fit_size(self, text: str) -> List[str]:
        if not text.strip():
            return []
        if len(text) <= self.max_chars:
            return [text]
        sentences = [s for s in _SENT_RE.split(text) if s.strip()]
        pieces: List[str] = []
        cur = ""
        for s in sentences:
            if cur and len(cur) + len(s) > self.max_chars:
                pieces.append(cur)
                cur = (cur[-self.overlap:] + s) if self.overlap else s
            else:
                cur += s
            # 单句超长（少见）：硬切，保持重叠
            while len(cur) > self.max_chars * 2:
                pieces.append(cur[: self.max_chars])
                cur = cur[self.max_chars - self.overlap:]
        if cur.strip():
            pieces.append(cur)
        return pieces

    # ---- 碎块合并 ----

    def _merge_small(self, raw: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
        merged: List[Tuple[str, str]] = []
        for heading, piece in raw:
            if merged and len(piece) < self.min_chars:
                prev_h, prev_p = merged[-1]
                merged[-1] = (prev_h, prev_p + "\n" + piece)
            else:
                merged.append((heading, piece))
        return merged

    # ---- 产出 ----

    def _record(self, index: int, heading: str, piece: str, doc_title: str) -> Dict:
        content = f"《{doc_title}》{piece}" if doc_title else piece
        return {
            "chunk_index": index,
            "chunk_type": self.chunk_type,
            "title": heading,
            "content": content,
            "metadata": {
                "heading": heading,
                "doc_title": doc_title,
                "char_count": len(piece),
                "word_count": len(piece),
            },
        }


class OfficialChunker(_BaseChunker):
    """公文文档切片器：按标题层级切分，再施加尺寸约束与重叠。"""

    SECTION_RE = (
        r"([一二三四五六七八九十]+[、．.]\s*|（[一二三四五六七八九十]+）\s*"
        r"|\d+[\.．]\s*|（\d+）\s*)"
        r"(.*?)"
        r"(?=([一二三四五六七八九十]+[、．.]\s*|（[一二三四五六七八九十]+）\s*"
        r"|\d+[\.．]\s*|（\d+）\s*)|$)"
    )
    chunk_type = "section"
    min_section_chars = 20


class LegalChunker(_BaseChunker):
    """法规文档切片器：按条款切分，再施加尺寸约束与重叠。"""

    SECTION_RE = (
        r"(第[一二三四五六七八九十百千零\d]+条[、\.]?\s*)"
        r"(.*?)"
        r"(?=(第[一二三四五六七八九十百千零\d]+条[、\.]?\s*)|$)"
    )
    chunk_type = "article"
    min_section_chars = 10
