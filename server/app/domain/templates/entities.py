"""写作模板领域实体。"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class WritingTemplate:
    name: str
    category: str
    content_template: str
    id: Optional[str] = None
    base_type: str = "公文"
    description: str = ""
    icon: str = "Document"
    params_schema: List[Dict[str, Any]] = field(default_factory=list)
    system_prompt: str = ""
    writing_style: str = "正式公文"
    word_count: int = 1000
    need_red_header: bool = False
    need_signature: bool = True
    need_date: bool = True
    need_doc_number: bool = False
    keywords: Optional[str] = None
    is_active: bool = True
    is_builtin: bool = False
    created_by: Optional[str] = None
    sort_order: int = 0
    use_count: int = 0
    # 新版字段
    template_kind: str = "official_doc"  # official_doc=公文模板 / writing_ref=写作参考模板
    tags: List[str] = field(default_factory=list)
    scene: str = ""
    writing_guide: str = ""
    structure: List[Dict[str, Any]] = field(default_factory=list)
    kb_ids: List[str] = field(default_factory=list)
    visibility: str = "official"  # official=官方 / personal=个人
    share_scope: str = "all"      # all / department / role
    share_departments: List[str] = field(default_factory=list)
    share_roles: List[str] = field(default_factory=list)
    is_draft: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def visible_to(self, user_id: str, user_role: str, user_department: str) -> bool:
        """可见性规则（与旧系统一致）：管理员全见；草稿仅创建者；个人模板仅创建者；
        官方模板按共享范围（全平台/部门/角色）过滤。"""
        from app.domain.identity.entities import ADMIN_OR_ABOVE
        if user_role in ADMIN_OR_ABOVE:
            return True
        if self.is_draft:
            return self.created_by == user_id
        if self.visibility == "personal":
            return self.created_by == user_id
        if self.share_scope == "all":
            return True
        if self.share_scope == "department":
            return bool(user_department) and user_department in (self.share_departments or [])
        if self.share_scope == "role":
            return user_role in (self.share_roles or [])
        return True


@dataclass
class TemplateCategory:
    name: str
    code: str
    id: Optional[str] = None
    description: str = ""
    icon: str = "Folder"
    sort_order: int = 0
    is_active: bool = True
    created_at: Optional[datetime] = None
