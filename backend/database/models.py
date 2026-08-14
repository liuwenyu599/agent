from sqlalchemy import create_engine, Column, String, DateTime, Integer, Boolean, JSON, ForeignKey, Text, BigInteger, Float
from sqlalchemy.sql import func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import uuid

Base = declarative_base()

def generate_uuid():
    return str(uuid.uuid4())

class User(Base):
    __tablename__ = "users"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    username = Column(String(100), unique=True, nullable=False)
    email = Column(String(200), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    real_name = Column(String(100))
    department = Column(String(100))
    role = Column(String(20), default="user")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    personal_kb = relationship("KnowledgeBase", back_populates="owner", foreign_keys="KnowledgeBase.owner_id")
    chat_sessions = relationship("ChatSession", back_populates="user")
    uploaded_docs = relationship("Document", back_populates="uploader", foreign_keys="Document.uploaded_by")

class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    kb_type = Column(String(20), default="public")
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    owner = relationship("User", back_populates="personal_kb", foreign_keys=[owner_id])
    documents = relationship("Document", back_populates="knowledge_base")

class Document(Base):
    __tablename__ = "documents"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    kb_id = Column(String(36), ForeignKey("knowledge_bases.id"), nullable=False)
    title = Column(String(500), nullable=False)
    doc_type = Column(String(50))
    department = Column(String(100))
    issue_date = Column(DateTime)
    doc_number = Column(String(100))
    file_path = Column(String(500))
    file_size = Column(BigInteger)
    page_count = Column(Integer)
    content = Column(Text)  # 文档内容
    
    status = Column(String(20), default="pending")
    uploaded_by = Column(String(36), ForeignKey("users.id"))
    created_by = Column(String(36), ForeignKey("users.id"))
    reviewed_by = Column(String(36), ForeignKey("users.id"))
    reviewed_at = Column(DateTime)
    review_comment = Column(Text)
    
    version = Column(Integer, default=1)
    doc_metadata = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    knowledge_base = relationship("KnowledgeBase", back_populates="documents")
    uploader = relationship("User", back_populates="uploaded_docs", foreign_keys=[uploaded_by])
    reviewer = relationship("User", foreign_keys=[reviewed_by])
    chunks = relationship("Chunk", back_populates="document", cascade="all, delete-orphan")

class Chunk(Base):
    __tablename__ = "chunks"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    doc_id = Column(String(36), ForeignKey("documents.id"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    chunk_type = Column(String(50))
    title = Column(String(500))
    content = Column(Text, nullable=False)
    char_count = Column(Integer)
    word_count = Column(Integer)
    embedding_model = Column(String(50))
    milvus_id = Column(String(50))
    es_id = Column(String(50))
    chunk_metadata = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    document = relationship("Document", back_populates="chunks")

class ChatSession(Base):
    __tablename__ = "chat_sessions"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    title = Column(String(200))
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="chat_sessions")
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")

class ChatMessage(Base):
    __tablename__ = "chat_messages"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    session_id = Column(String(36), ForeignKey("chat_sessions.id"), nullable=False)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    source = Column(String(50), default="chat", comment="消息来源: chat/template")
    sources = Column(JSON)
    tool_calls = Column(JSON)
    tokens_used = Column(Integer)
    latency_ms = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    session = relationship("ChatSession", back_populates="messages")

class AuditLog(Base):
    __tablename__ = "audit_logs"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id"))
    action = Column(String(50), nullable=False)
    resource_type = Column(String(50))
    resource_id = Column(String(36))
    detail = Column(JSON)
    ip_address = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)

class PromptTemplate(Base):
    __tablename__ = "prompt_templates"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(100), unique=True, nullable=False)
    category = Column(String(50))
    description = Column(Text)
    template = Column(Text, nullable=False)
    variables = Column(JSON)
    is_active = Column(Boolean, default=True)
    created_by = Column(String(36), ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class SessionSummary(Base):
    __tablename__ = "session_summaries"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    session_id = Column(String(36), ForeignKey("chat_sessions.id"), nullable=False)
    summary = Column(Text, nullable=False)
    key_points = Column(JSON)  # 关键要点
    message_count = Column(Integer, default=0)  # 总结时的消息数
    created_at = Column(DateTime, default=datetime.utcnow)

class UserMemory(Base):
    __tablename__ = "user_memories"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    memory_type = Column(String(50), nullable=False)  # department, preference, topic, etc.
    content = Column(Text, nullable=False)
    importance = Column(Float, default=0.5)  # 0-1
    source = Column(String(50))  # explicit, inferred, system
    last_accessed = Column(DateTime, default=datetime.utcnow)
    access_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ===== 写作模板模型 =====

class WritingTemplate(Base):
    __tablename__ = "writing_templates"
    __table_args__ = {'extend_existing': True}
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False, comment="模板名称")
    category = Column(String(50), nullable=False, comment="模板分类")
    description = Column(Text, comment="模板描述")
    icon = Column(String(50), default="Document", comment="图标名称")
    params_schema = Column(JSON, default=list, comment="参数 schema")
    content_template = Column(Text, nullable=False, comment="内容模板")
    system_prompt = Column(Text, comment="系统提示词模板")
    is_active = Column(Boolean, default=True, comment="是否启用")
    is_builtin = Column(Boolean, default=False, comment="是否内置模板")
    created_by = Column(String(36), ForeignKey("users.id"), comment="创建者")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    sort_order = Column(Integer, default=0, comment="排序")
    use_count = Column(Integer, default=0, comment="使用次数")
    base_type = Column(String(50), default="公文", comment="基础类型")
    writing_style = Column(String(50), default="正式公文", comment="写作风格")
    word_count = Column(Integer, default=1000, comment="字数要求")
    need_red_header = Column(Boolean, default=False, comment="是否需要红头")
    need_signature = Column(Boolean, default=True, comment="是否需要落款")
    need_date = Column(Boolean, default=True, comment="是否需要日期")
    need_doc_number = Column(Boolean, default=False, comment="是否需要文号")
    keywords = Column(Text, nullable=True, comment="关键词/补充说明，传给AI的额外指令")


class TemplateCategory(Base):
    __tablename__ = "template_categories"
    __table_args__ = {'extend_existing': True}
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(50), nullable=False, comment="分类名称")
    code = Column(String(50), nullable=False, unique=True, comment="分类代码")
    description = Column(Text, comment="分类描述")
    icon = Column(String(50), default="Folder", comment="图标")
    sort_order = Column(Integer, default=0, comment="排序")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
