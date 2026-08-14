from typing import List, Dict, Optional
from sqlalchemy.orm import Session

from backend.database.models import KnowledgeBase, Document, User

class KnowledgeManager:
    def __init__(self, db: Session):
        self.db = db
    
    def get_or_create_personal_kb(self, user_id: str) -> KnowledgeBase:
        """获取或创建个人知识库"""
        kb = self.db.query(KnowledgeBase).filter(
            KnowledgeBase.kb_type == "personal",
            KnowledgeBase.owner_id == user_id
        ).first()
        
        if not kb:
            kb = KnowledgeBase(
                name="个人知识库",
                description="用户个人上传的文档",
                kb_type="personal",
                owner_id=user_id
            )
            self.db.add(kb)
            self.db.commit()
        
        return kb
    
    def list_accessible_kbs(self, user_id: str, user_role: str) -> List[KnowledgeBase]:
        """列出用户可访问的知识库"""
        query = self.db.query(KnowledgeBase)
        
        if user_role == "admin":
            # 管理员可访问所有
            return query.all()
        
        # 普通用户：公共 + 个人
        return query.filter(
            (KnowledgeBase.kb_type == "public") |
            ((KnowledgeBase.kb_type == "personal") & (KnowledgeBase.owner_id == user_id))
        ).all()
    
    def create_public_kb(self, name: str, description: str = "") -> KnowledgeBase:
        """创建公共知识库（仅管理员）"""
        kb = KnowledgeBase(
            name=name,
            description=description,
            kb_type="public"
        )
        self.db.add(kb)
        self.db.commit()
        return kb
