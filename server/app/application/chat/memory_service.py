"""会话记忆服务（移植自旧 services/memory_service.py）。"""
import re
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.shared.writing_assistant import WritingAssistant
from app.core.logging import get_logger
from app.infrastructure.database.models.chat import (
    ChatMessageModel,
    SessionSummaryModel,
    UserMemoryModel,
)

logger = get_logger(__name__)


class MemoryService:
    def __init__(self, assistant: WritingAssistant) -> None:
        self.assistant = assistant

    def get_session_context(self, session_id: str, db: Session,
                            max_history: int = 20) -> List[Dict]:
        """最近 N 条完整对话（含用户和助手），按时间正序返回。"""
        messages = db.scalars(
            select(ChatMessageModel)
            .where(ChatMessageModel.session_id == session_id)
            .order_by(ChatMessageModel.created_at.desc())
            .limit(max_history)
        ).all()
        return [{"role": m.role, "content": m.content} for m in reversed(messages)]

    def get_full_session_history(self, session_id: str, db: Session) -> List[Dict]:
        messages = db.scalars(
            select(ChatMessageModel)
            .where(ChatMessageModel.session_id == session_id)
            .order_by(ChatMessageModel.created_at.asc())
        ).all()
        return [{"role": m.role, "content": m.content} for m in messages]

    def summarize_session(self, session_id: str, db: Session) -> Optional[str]:
        messages = self.get_full_session_history(session_id, db)
        if len(messages) < 10:
            return None

        dialog_text = "\n".join(
            f"{m['role']}: {m['content'][:200]}" for m in messages
        )
        prompt = f"""请总结以下对话的关键信息：

{dialog_text}

请用2-3句话总结用户的主要意图和关键信息。只输出总结内容。"""

        summary = self.assistant.complete([
            {"role": "system", "content": "你是一个对话摘要助手。"},
            {"role": "user", "content": prompt},
        ], max_tokens=200)

        db_summary = SessionSummaryModel(
            session_id=session_id,
            summary=summary,
            key_points=self._extract_key_points(summary),
            message_count=len(messages),
        )
        db.add(db_summary)
        db.commit()
        return summary

    @staticmethod
    def _extract_key_points(summary: str) -> List[str]:
        points = [p.strip() for p in summary.split("。") if len(p.strip()) > 5]
        return points[:5]

    def get_user_memory(self, user_id: str, db: Session, query: str = None) -> List[Dict]:
        memories = db.scalars(
            select(UserMemoryModel)
            .where(UserMemoryModel.user_id == user_id)
            .order_by(UserMemoryModel.importance.desc(),
                      UserMemoryModel.last_accessed.desc())
        ).all()

        for m in memories[:5]:
            m.last_accessed = datetime.utcnow()
            m.access_count = (m.access_count or 0) + 1
        db.commit()

        return [{"type": m.memory_type, "content": m.content, "importance": m.importance}
                for m in memories]

    def add_user_memory(self, user_id: str, memory_type: str, content: str,
                        importance: float = 0.5, source: str = "inferred",
                        db: Session = None):
        existing = db.scalar(select(UserMemoryModel).where(
            UserMemoryModel.user_id == user_id,
            UserMemoryModel.memory_type == memory_type,
            UserMemoryModel.content == content,
        ))

        if existing:
            existing.importance = max(existing.importance, importance)
            existing.updated_at = datetime.utcnow()
        else:
            db.add(UserMemoryModel(
                user_id=user_id, memory_type=memory_type, content=content,
                importance=importance, source=source,
            ))
        db.commit()

    def extract_memory_from_message(self, user_id: str, message: str, db: Session):
        """从用户消息中提取长期记忆（姓名/职位/部门/偏好/工作）。"""
        name_patterns = [
            r"我是([一-龥]{2,8})(?:部长|局长|处长|科长|主任|书记|经理|工程师|教授|博士|硕士|同学)?",
            r"我叫([一-龥]{2,8})",
            r"我的名字是([一-龥]{2,8})",
            r"称呼我([一-龥]{2,8})",
        ]
        for pattern in name_patterns:
            match = re.search(pattern, message)
            if match:
                self.add_user_memory(user_id, "name", f"用户名叫{match.group(1)}",
                                     importance=0.9, source="explicit", db=db)
                break

        position_patterns = [
            r"([一-龥]{2,20}(?:部|局|处|科|院|所|中心|办公室))(?:的)?(?:部长|局长|处长|科长|主任|书记)",
            r"(?:担任|任职于|在|是)([一-龥]{2,20}(?:部|局|处|科|院|所|中心|办公室))(?:的)?(?:部长|局长|处长|科长|主任|书记)",
        ]
        for pattern in position_patterns:
            match = re.search(pattern, message)
            if match:
                self.add_user_memory(user_id, "position",
                                     f"用户的职位/身份：{match.group(0)}",
                                     importance=0.85, source="explicit", db=db)
                break

        dept_match = re.search(r"([^\s]{2,10}科|[^\s]{2,10}处|[^\s]{2,10}局|[^\s]{2,10}部|[^\s]{2,10}院)", message)
        if dept_match:
            self.add_user_memory(user_id, "department",
                                 f"用户在{dept_match.group(1)}工作",
                                 importance=0.8, source="inferred", db=db)

        preference_patterns = [
            r"我喜欢(.{2,30})", r"我讨厌(.{2,30})", r"我需要(.{2,30})",
            r"我想要(.{2,30})", r"我负责(.{2,30})", r"我主管(.{2,30})",
        ]
        for pattern in preference_patterns:
            match = re.search(pattern, message)
            if match:
                self.add_user_memory(user_id, "preference", f"用户{match.group(0)}",
                                     importance=0.7, source="explicit", db=db)
                break

        work_patterns = [
            r"(?:正在|负责|参与|主管)(.{3,30})(?:项目|工作|任务|工程)",
            r"(.{3,30})(?:项目|工作|任务)正在推进",
        ]
        for pattern in work_patterns:
            match = re.search(pattern, message)
            if match:
                self.add_user_memory(user_id, "work", f"用户的工作：{match.group(0)}",
                                     importance=0.75, source="explicit", db=db)
                break
