"""文号序号表。（代字, 年份）维度自增，保证同年同代字不重复。"""
from sqlalchemy import Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, generate_uuid


class DocNumberSequenceModel(Base):
    __tablename__ = "doc_number_sequences"
    __table_args__ = (
        UniqueConstraint("daizi", "year", name="uq_docnum_daizi_year"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                    default=generate_uuid)
    daizi: Mapped[str] = mapped_column(String(20), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    next_seq: Mapped[int] = mapped_column(Integer, nullable=False,
                                          default=1)
