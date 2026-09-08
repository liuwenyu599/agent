"""内容校验：核查生成内容与已知来源是否有出入。

核查权重（从高到低）：
1. 知识库：本次 RAG 实际检索到的材料（单位内部依据，权重最高）
2. 公开规则：文号年份合理性、《》文件名称规范性等公开可验证规则
3. 模型自述：模型生成但以上两层都验证不了的内容 → 标记待核实

不做的事：
- 不联网核查（内网部署前提）
- 不修改正文，只标记出入
- 正文中的历史引用本身不算问题，只校验其合理性与可追溯性
"""
import re
from typing import Any, Dict, List, Optional

from app.application.writing.postprocessor import _parse_date_year

# 《...》文件引用
CITATION_RE = re.compile(r"《([^《》\n]{2,50})》")

# 正文中的文号引用（文头程序注入文号除外，由调用方传入排除）
BODY_DOCNUM_RE = re.compile(
    r"[\u4e00-\u9fa5]{1,10}〔(\d{4})〕(\d+)号"
)

# 过于宽泛、不算具体引用的书名
GENERIC_TITLES = {
    "中华人民共和国宪法", "中华人民共和国民法典", "中华人民共和国刑法",
    "中华人民共和国行政处罚法", "中华人民共和国行政许可法",
    "中华人民共和国行政复议法", "中华人民共和国政府信息公开条例",
}


class ContentChecker:
    """生成内容 vs 已知来源核对。"""

    def check(
        self,
        text: str,
        sources: Optional[List[Dict]] = None,
        header_docnum: Optional[str] = None,
    ) -> Dict[str, Any]:
        issues: List[Dict[str, Any]] = []
        kb_text = "\n".join(
            s.get("content", "") for s in (sources or [])
        )

        # ---- 1. 《》文件引用核查 ----
        citations = list(dict.fromkeys(CITATION_RE.findall(text)))
        kb_verified, unverified = [], []
        for title in citations:
            clean = title.strip()
            if clean in GENERIC_TITLES:
                kb_verified.append({"title": clean, "via": "公开法规"})
                continue
            if kb_text and clean in kb_text:
                kb_verified.append({"title": clean, "via": "知识库"})
            elif not kb_text:
                unverified.append(clean)
            else:
                unverified.append(clean)
        for title in unverified[:5]:
            issues.append({
                "source": "content",
                "severity": "review",
                "message": f"《{title}》未在本次检索到的知识库材料中找到，"
                           f"请核实该文件名称与内容",
            })

        # ---- 2. 正文文号引用合理性 ----
        for m in BODY_DOCNUM_RE.finditer(text):
            num_text = m.group(0)
            if header_docnum and num_text == header_docnum:
                continue
            year = int(m.group(1))
            if not (1949 <= year <= _current_year()):
                issues.append({
                    "source": "content",
                    "severity": "review",
                    "message": f"引用文号“{num_text}”年份异常，请核实",
                })

        # ---- 3. 落款日期与正文事实年份冲突粗查 ----
        # 正文若声称"今年/去年"等相对年份，与当前年份对齐检查
        body_years = re.findall(r"(20\d{2})年", text)
        future_years = {
            y for y in body_years if int(y) > _current_year() + 1
        }
        for y in sorted(future_years)[:3]:
            issues.append({
                "source": "content",
                "severity": "review",
                "message": f"正文出现未来年份 {y} 年，如非工作目标年份请核实",
            })

        verified_count = len(kb_verified)
        return {
            "citations_total": len(citations),
            "kb_verified": kb_verified[:10],
            "unverified": unverified[:10],
            "verified_ratio": (
                round(verified_count / len(citations), 2)
                if citations else None
            ),
            "issues": issues,
            "note": "核查权重：知识库 > 公开规则 > 模型自述；"
                    "未核实项请人工确认后使用",
        }


def _current_year() -> int:
    from datetime import date
    return date.today().year
