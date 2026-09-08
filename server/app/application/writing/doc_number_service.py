"""程序文号生成服务。

当前文件文号由程序生成，LLM 禁止自由生成。
序号按（代字, 年份）在数据库中自增，保证同年不重复。
序号策略可替换：换实现时保持 next_number(daizi) 签名即可。
"""
from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.infrastructure.database.models.doc_number import (
    DocNumberSequenceModel,
)

logger = get_logger(__name__)


class DocNumberService:
    def __init__(self, db: Optional[Session]) -> None:
        self.db = db

    def next_number(self, daizi: Optional[str] = None) -> str:
        """生成下一个文号，如 粤府办〔2026〕001号。"""
        daizi = daizi or settings.DOC_NUMBER_DEFAULT_DAIZI
        year = date.today().year
        seq = self._next_seq(daizi, year)
        return f"{daizi}〔{year}〕{seq:03d}号"

    def _next_seq(self, daizi: str, year: int) -> int:
        if self.db is None:
            return 1
        try:
            row = self.db.scalars(
                select(DocNumberSequenceModel).where(
                    DocNumberSequenceModel.daizi == daizi,
                    DocNumberSequenceModel.year == year,
                )
            ).first()
            if row is None:
                row = DocNumberSequenceModel(
                    daizi=daizi, year=year, next_seq=1
                )
                self.db.add(row)
                self.db.flush()
            seq = row.next_seq
            row.next_seq = seq + 1
            self.db.flush()
            return seq
        except Exception as e:  # noqa: BLE001
            # 文号服务不可用时降级为固定序号，不阻塞生成
            logger.warning("[文号] 序号服务降级: %s", e)
            self.db.rollback()
            return 1
