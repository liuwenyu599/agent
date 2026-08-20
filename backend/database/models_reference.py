# -*- coding: utf-8 -*-
"""写作参考材料数据模型（新文件：backend/database/models_reference.py）

两类材料与知识库 Document 严格分离（需求五、十三）：

- TemplateReference：模板固定参考材料（persistent）
  管理员为某写作模板配置的历史优秀稿件/常用范式，随模板长期存在，
  只用于让 AI 学习"标题风格、行文方式、叙事结构"，不作为事实来源。

- TaskReference：当前任务佐证材料（不进入知识库，默认不长期保留）
  用户为"这一次写作"上传/粘贴/添加的材料，是写作的事实依据，
  只有归属用户本人可见可用，不会被其他用户通过知识库检索到。
  用户主动点"加入知识库"时，才转换为知识库 Document。

表通过 Base.metadata 注册，main.py 的 create_all 会自动建表，无需迁移脚本。
"""
import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Text, BigInteger

from backend.database.models import Base


def _uuid():
    return str(uuid.uuid4())


class TemplateReference(Base):
    """模板固定参考材料（范式学习用，不入知识库）"""
    __tablename__ = "template_references"

    id = Column(String(36), primary_key=True, default=_uuid)
    template_id = Column(String(36), ForeignKey("writing_templates.id"), nullable=False, index=True)
    name = Column(String(500), nullable=False, comment="材料名称/标题")
    ref_type = Column(String(20), nullable=False, comment="file / text / url")
    file_path = Column(String(500), comment="ref_type=file 时的存储路径")
    file_size = Column(BigInteger)
    source_url = Column(String(1000), comment="ref_type=url 时的原始链接")
    text_content = Column(Text, comment="解析/粘贴后的纯文本")
    char_count = Column(BigInteger, default=0)
    parse_status = Column(String(20), default="ok", comment="ok / partial / failed")
    parse_note = Column(String(500))
    created_by = Column(String(36), ForeignKey("users.id"))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class TaskReference(Base):
    """当前写作任务佐证材料（事实依据，不入知识库，仅归属用户可见）"""
    __tablename__ = "task_references"

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    template_id = Column(String(36), ForeignKey("writing_templates.id"), nullable=True, index=True)
    session_id = Column(String(36), ForeignKey("chat_sessions.id"), nullable=True,
                        comment="开始写作后绑定到对话")
    name = Column(String(500), nullable=False, comment="材料名称/标题")
    ref_type = Column(String(20), nullable=False, comment="file / text / url")
    file_path = Column(String(500))
    file_size = Column(BigInteger)
    source_url = Column(String(1000))
    text_content = Column(Text)
    char_count = Column(BigInteger, default=0)
    parse_status = Column(String(20), default="ok")
    parse_note = Column(String(500))
    promoted_doc_id = Column(String(36), comment="加入知识库后对应的 documents.id")
    created_at = Column(DateTime, default=datetime.utcnow)
