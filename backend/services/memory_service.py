from typing import List, Dict, Optional
from sqlalchemy.orm import Session
from datetime import datetime
import re

from backend.database.models import ChatMessage, SessionSummary, UserMemory
from backend.services.llm_service import LLMService

class MemoryService:
    def __init__(self, llm_service: LLMService):
        self.llm = llm_service
    
    def get_session_context(self, session_id: str, db: Session, max_history: int = 20) -> List[Dict]:
        """
        获取会话完整上下文：
        - 返回最近 N 轮完整对话（包含用户和助手）
        - 这样 LLM 能看到完整的对话历史，理解指代和省略
        """
        messages = db.query(ChatMessage).filter(
            ChatMessage.session_id == session_id
        ).order_by(ChatMessage.created_at.desc()).limit(max_history).all()
        
        # 反转顺序（从早到晚）
        return [{"role": m.role, "content": m.content} for m in reversed(messages)]
    
    def get_full_session_history(self, session_id: str, db: Session) -> List[Dict]:
        """获取会话全部历史（用于总结）"""
        messages = db.query(ChatMessage).filter(
            ChatMessage.session_id == session_id
        ).order_by(ChatMessage.created_at.asc()).all()
        
        return [{"role": m.role, "content": m.content} for m in messages]
    
    def summarize_session(self, session_id: str, db: Session) -> Optional[str]:
        """总结会话历史，生成摘要"""
        messages = self.get_full_session_history(session_id, db)
        
        if len(messages) < 10:
            return None
        
        dialog_text = "\n".join([
            f"{m['role']}: {m['content'][:200]}" 
            for m in messages
        ])
        
        prompt = f"""请总结以下对话的关键信息：

{dialog_text}

请用2-3句话总结用户的主要意图和关键信息。只输出总结内容。"""

        summary = self.llm._call_vllm([
            {"role": "system", "content": "你是一个对话摘要助手。"},
            {"role": "user", "content": prompt}
        ], max_tokens=200)
        
        from backend.database.models import SessionSummary as SummaryModel
        db_summary = SummaryModel(
            session_id=session_id,
            summary=summary,
            key_points=self._extract_key_points(summary),
            message_count=len(messages)
        )
        db.add(db_summary)
        db.commit()
        
        return summary
    
    def _extract_key_points(self, summary: str) -> List[str]:
        points = [p.strip() for p in summary.split("。") if len(p.strip()) > 5]
        return points[:5]
    
    def get_user_memory(self, user_id: str, db: Session, query: str = None) -> List[Dict]:
        """获取用户长期记忆"""
        memories = db.query(UserMemory).filter(
            UserMemory.user_id == user_id
        ).order_by(UserMemory.importance.desc(), UserMemory.last_accessed.desc()).all()
        
        for m in memories[:5]:
            m.last_accessed = datetime.utcnow()
            m.access_count += 1
        
        db.commit()
        
        return [{
            "type": m.memory_type,
            "content": m.content,
            "importance": m.importance
        } for m in memories]
    
    def add_user_memory(self, user_id: str, memory_type: str, content: str, 
                       importance: float = 0.5, source: str = "inferred", db: Session = None):
        """添加用户记忆"""
        existing = db.query(UserMemory).filter(
            UserMemory.user_id == user_id,
            UserMemory.memory_type == memory_type,
            UserMemory.content == content
        ).first()
        
        if existing:
            existing.importance = max(existing.importance, importance)
            existing.updated_at = datetime.utcnow()
        else:
            memory = UserMemory(
                user_id=user_id,
                memory_type=memory_type,
                content=content,
                importance=importance,
                source=source
            )
            db.add(memory)
        
        db.commit()
    
    def extract_memory_from_message(self, user_id: str, message: str, db: Session):
        """从用户消息中提取记忆"""
        
        # 1. 提取姓名/身份
        name_patterns = [
            r"我是([一-龥]{2,8})(?:部长|局长|处长|科长|主任|书记|经理|工程师|教授|博士|硕士|同学)?",
            r"我叫([一-龥]{2,8})",
            r"我的名字是([一-龥]{2,8})",
            r"称呼我([一-龥]{2,8})",
        ]
        for pattern in name_patterns:
            match = re.search(pattern, message)
            if match:
                name = match.group(1)
                self.add_user_memory(
                    user_id=user_id,
                    memory_type="name",
                    content=f"用户名叫{name}",
                    importance=0.9,
                    source="explicit",
                    db=db
                )
                break
        
        # 2. 提取职位/身份
        position_patterns = [
            r"([一-龥]{2,20}(?:部|局|处|科|院|所|中心|办公室))(?:的)?(?:部长|局长|处长|科长|主任|书记)",
            r"(?:担任|任职于|在|是)([一-龥]{2,20}(?:部|局|处|科|院|所|中心|办公室))(?:的)?(?:部长|局长|处长|科长|主任|书记)",
        ]
        for pattern in position_patterns:
            match = re.search(pattern, message)
            if match:
                position = match.group(0)
                self.add_user_memory(
                    user_id=user_id,
                    memory_type="position",
                    content=f"用户的职位/身份：{position}",
                    importance=0.85,
                    source="explicit",
                    db=db
                )
                break
        
        # 3. 提取部门信息
        dept_match = re.search(r"([^\s]{2,10}科|[^\s]{2,10}处|[^\s]{2,10}局|[^\s]{2,10}部|[^\s]{2,10}院)", message)
        if dept_match:
            self.add_user_memory(
                user_id=user_id,
                memory_type="department",
                content=f"用户在{dept_match.group(1)}工作",
                importance=0.8,
                source="inferred",
                db=db
            )
        
        # 4. 提取偏好/需求
        preference_patterns = [
            r"我喜欢(.{2,30})",
            r"我讨厌(.{2,30})",
            r"我需要(.{2,30})",
            r"我想要(.{2,30})",
            r"我负责(.{2,30})",
            r"我主管(.{2,30})",
        ]
        for pattern in preference_patterns:
            match = re.search(pattern, message)
            if match:
                self.add_user_memory(
                    user_id=user_id,
                    memory_type="preference",
                    content=f"用户{match.group(0)}",
                    importance=0.7,
                    source="explicit",
                    db=db
                )
                break
        
        # 5. 提取工作/项目相关
        work_patterns = [
            r"(?:正在|负责|参与|主管)(.{3,30})(?:项目|工作|任务|工程)",
            r"(.{3,30})(?:项目|工作|任务)正在推进",
        ]
        for pattern in work_patterns:
            match = re.search(pattern, message)
            if match:
                self.add_user_memory(
                    user_id=user_id,
                    memory_type="work",
                    content=f"用户的工作：{match.group(0)}",
                    importance=0.75,
                    source="explicit",
                    db=db
                )
                break
