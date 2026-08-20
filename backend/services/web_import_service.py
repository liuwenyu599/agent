# -*- coding: utf-8 -*-
"""网页链接批量导入知识库服务（新文件：backend/services/web_import_service.py）

处理流程（需求一）：
    URL/Excel → 读取 URL → 去重 → 抓取网页 → 提取标题/正文/时间/来源
    → 生成知识库文档 → 分块 → Embedding → 进入现有 RAG（复用 DocumentService）

关键规则：
- 部分成功：单个 URL 失败不影响其他（需求二）；
- 三层去重：本批内 URL 去重、库内 source_url 去重、归档文档也算已存在；
- Excel 元数据（标题/媒体/刊发时间）优先，网页解析结果兜底。
"""
import re
from io import BytesIO
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from backend.services.web_fetcher import fetch_webpage, looks_like_url, extract_urls_from_text

# Excel 表头别名（兼容不同叫法）
_TITLE_KEYS = ["标题", "宣传信息标题", "信息标题", "题名", "title"]
_SOURCE_KEYS = ["媒体或刊物", "媒体/刊物", "来源", "媒体", "刊物", "source"]
_TIME_KEYS = ["刊发时间", "发布时间", "日期", "时间", "publish_time"]
_URL_KEYS = ["佐证材料", "链接", "网址", "url", "URL", "链接地址"]


def _norm(s) -> str:
    return re.sub(r"\s+", "", str(s or "")).lower()


def parse_urls_from_excel(data: bytes, filename: str = "") -> List[Dict]:
    """从 Excel 读取 URL 行。

    返回 [{"url", "title", "source_name", "publish_time"}, ...]
    - 优先识别"佐证材料/链接/url"列；识别不到则在所有单元格中找 http(s) 链接；
    - 同 sheet 多 sheet 都遍历；
    - 表头行自动跳过。
    """
    try:
        import openpyxl
    except ImportError:
        raise ValueError("服务器缺少 openpyxl，无法解析 Excel，请先 pip install openpyxl")

    wb = openpyxl.load_workbook(BytesIO(data), read_only=True, data_only=True)
    rows_out: List[Dict] = []

    for ws in wb.worksheets:
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        if not rows:
            continue

        # 找表头行（含"标题/佐证材料/链接"等字样的行），找不到就把第一行当表头
        header_idx = 0
        for i, row in enumerate(rows[:5]):
            joined = "".join(_norm(c) for c in row if c is not None)
            if any(_norm(k) in joined for k in _TITLE_KEYS + _URL_KEYS):
                header_idx = i
                break

        header = [str(c).strip() if c is not None else "" for c in rows[header_idx]]

        def _col(keys):
            for k in keys:
                for j, h in enumerate(header):
                    if _norm(k) == _norm(h) or _norm(k) in _norm(h):
                        return j
            return None

        c_title, c_src, c_time, c_url = _col(_TITLE_KEYS), _col(_SOURCE_KEYS), _col(_TIME_KEYS), _col(_URL_KEYS)

        for row in rows[header_idx + 1:]:
            if not row or all(c is None or str(c).strip() == "" for c in row):
                continue
            cells = ["" if c is None else str(c).strip() for c in row]

            urls = []
            if c_url is not None and c_url < len(cells):
                urls = extract_urls_from_text(cells[c_url])
            if not urls:
                # 兜底：整行所有单元格找链接
                urls = extract_urls_from_text(" ".join(cells))
            if not urls:
                continue

            for u in urls:
                rows_out.append({
                    "url": u,
                    "title": cells[c_title] if c_title is not None and c_title < len(cells) else "",
                    "source_name": cells[c_src] if c_src is not None and c_src < len(cells) else "",
                    "publish_time": cells[c_time] if c_time is not None and c_time < len(cells) else "",
                })

    wb.close()
    return rows_out


class WebImportService:
    """网页链接批量导入知识库"""

    def __init__(self, doc_service):
        # doc_service: DocumentService 实例（带 embedder），复用其网页入库与查重
        self.doc_service = doc_service

    def import_urls(self, db: Session, kb_id: str, user_id: str, user_role: str,
                    items: List[Dict]) -> Dict:
        """批量导入。items: [{"url", "title"?, "source_name"?, "publish_time"?}, ...]

        返回 {"total", "success": [...], "duplicated": [...], "failed": [...]}
        单个失败绝不影响整体（需求二）。
        """
        success, duplicated, failed = [], [], []
        seen_in_batch = set()

        for item in items:
            url = (item.get("url") or "").strip()
            if not url:
                continue

            # 1) 本批内去重
            if url in seen_in_batch:
                duplicated.append({"url": url, "title": item.get("title", ""),
                                   "reason": "本批次内重复"})
                continue
            seen_in_batch.add(url)

            # 2) 库内去重（含已归档文档）
            try:
                if self.doc_service.find_by_source_url(db, url):
                    duplicated.append({"url": url, "title": item.get("title", ""),
                                       "reason": "知识库中已存在相同链接"})
                    continue
            except Exception as e:
                # 查重异常不阻断导入，仅记录日志
                print(f"[WebImport] 查重异常（继续导入）: {e}")

            # 3) 抓取
            fetched = fetch_webpage(url)
            if not fetched.get("ok"):
                failed.append({"url": url, "title": item.get("title", "") or fetched.get("title", ""),
                               "reason": fetched.get("error", "抓取失败")})
                continue

            # 4) 入库（Excel 元数据优先，网页解析兜底）
            try:
                r = self.doc_service.process_web_document(
                    db=db, kb_id=kb_id, user_id=user_id, user_role=user_role,
                    url=url, fetched=fetched,
                    title=item.get("title") or None,
                    source_name=item.get("source_name") or None,
                    publish_time=item.get("publish_time") or None,
                )
                success.append({"url": url, "title": r["title"], "doc_id": r["doc_id"],
                                "status": r["status"]})
            except Exception as e:
                db.rollback()
                failed.append({"url": url, "title": item.get("title", "") or fetched.get("title", ""),
                               "reason": f"入库失败: {e}"})

        return {
            "total": len(seen_in_batch) + len([d for d in duplicated if d["reason"] == "本批次内重复"]),
            "success": success,
            "duplicated": duplicated,
            "failed": failed,
            "success_count": len(success),
            "duplicated_count": len(duplicated),
            "failed_count": len(failed),
        }
