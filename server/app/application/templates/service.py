"""模板业务服务（移植旧 api/templates.py 的业务规则）。"""
from typing import List, Optional

from sqlalchemy.orm import Session

from app.application.templates.builtin_data import (
    _DEPRECATED_BUILTIN_NAMES,
    _DEPRECATED_CATEGORY_NAMES,
    BUILTIN_CATEGORIES,
    BUILTIN_TEMPLATES,
)
from app.application.templates.dto import TemplateCreateRequest, TemplateUpdateRequest
from app.core.exceptions import AppError, NotFoundError, PermissionDeniedError
from app.domain.identity.entities import ADMIN_OR_ABOVE, ROLE_DEVELOPER, User
from app.domain.templates.entities import TemplateCategory, WritingTemplate
from app.infrastructure.repositories.templates import (
    SqlAlchemyTemplateCategoryRepository,
    SqlAlchemyWritingTemplateRepository,
)


class TemplateService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.templates = SqlAlchemyWritingTemplateRepository(db)
        self.categories = SqlAlchemyTemplateCategoryRepository(db)

    # ---- 初始化（幂等） ----
    def init_builtin(self, admin: User) -> dict:
        for cat in BUILTIN_CATEGORIES:
            if not self.categories.get_by_code(cat["code"]):
                self.categories.add(TemplateCategory(**cat))

        self.categories.deactivate_codes([
            "plan_summary", "request_report", "notice", "research", "meeting",
            "report", "legal_doc", "work_summary", "work_plan",
        ])
        self.templates.deactivate_builtin_in(
            _DEPRECATED_CATEGORY_NAMES + _DEPRECATED_BUILTIN_NAMES
        )

        count = 0
        updated = 0
        for t in BUILTIN_TEMPLATES:
            existing = self.templates.find_builtin_by_name(t["name"])
            if existing:
                existing.category = t["category"]
                existing.base_type = t.get("base_type", "公文")
                existing.description = t.get("description", "")
                existing.icon = t["icon"]
                existing.params_schema = t["params_schema"]
                existing.content_template = t["content_template"]
                existing.system_prompt = t.get("system_prompt", "")
                existing.writing_style = t.get("writing_style", "正式公文")
                existing.word_count = t.get("word_count", 1000)
                existing.need_red_header = t.get("need_red_header", False)
                existing.need_signature = t.get("need_signature", True)
                existing.need_date = t.get("need_date", True)
                existing.need_doc_number = t.get("need_doc_number", False)
                existing.keywords = t.get("keywords", None)
                existing.is_active = True
                self.templates.update(existing)
                updated += 1
                continue
            self.templates.add(WritingTemplate(
                name=t["name"], category=t["category"],
                base_type=t.get("base_type", "公文"), icon=t["icon"],
                description=t.get("description", ""),
                params_schema=t["params_schema"],
                content_template=t["content_template"],
                system_prompt=t.get("system_prompt", ""),
                writing_style=t.get("writing_style", "正式公文"),
                word_count=t.get("word_count", 1000),
                need_red_header=t.get("need_red_header", False),
                need_signature=t.get("need_signature", True),
                need_date=t.get("need_date", True),
                need_doc_number=t.get("need_doc_number", False),
                keywords=t.get("keywords", None),
                is_builtin=True, is_active=True, created_by=admin.id, sort_order=0,
            ))
            count += 1

        return {"message": f"Initialized {count} builtin templates, updated {updated}"}

    # ---- 分类 ----
    def list_categories(self) -> List[dict]:
        return [{"id": c.id, "name": c.name, "code": c.code, "icon": c.icon,
                 "description": c.description} for c in self.categories.list_active()]

    def create_category(self, name: str, code: str, description: str = "",
                        icon: str = "Folder", sort_order: int = 0) -> dict:
        if self.categories.get_by_code(code):
            raise AppError(400, "Category code already exists")
        cat = self.categories.add(TemplateCategory(
            name=name, code=code, description=description, icon=icon, sort_order=sort_order,
        ))
        return {"id": cat.id, "message": "Category created"}

    # ---- 模板 ----
    def list_templates(self, user: User, category: Optional[str] = None) -> List[dict]:
        templates = self.templates.list_active(category)
        templates = [t for t in templates
                     if t.visible_to(user.id, user.role, user.department)]
        return [self._to_list_dict(t) for t in templates]

    def _to_list_dict(self, t: WritingTemplate) -> dict:
        return {
            "id": t.id, "name": t.name, "category": t.category, "base_type": t.base_type,
            "description": t.description, "icon": t.icon, "params_schema": t.params_schema,
            "is_builtin": t.is_builtin, "use_count": t.use_count,
            "writing_style": t.writing_style, "word_count": t.word_count,
            "need_red_header": t.need_red_header, "need_signature": t.need_signature,
            "need_date": t.need_date, "need_doc_number": t.need_doc_number,
            "keywords": t.keywords,
            "template_kind": t.template_kind, "tags": t.tags or [],
            "scene": t.scene or "", "writing_guide": t.writing_guide or "",
            "structure": t.structure or [], "kb_ids": t.kb_ids or [],
            "visibility": t.visibility, "share_scope": t.share_scope,
            "share_departments": t.share_departments or [],
            "share_roles": t.share_roles or [],
            "is_draft": bool(t.is_draft),
            "created_by_name": self.templates.creator_name(t.created_by),
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }

    def get_template(self, template_id: str) -> dict:
        t = self.templates.get(template_id)
        if not t:
            raise NotFoundError("Template not found")
        return {
            "id": t.id, "name": t.name, "category": t.category, "base_type": t.base_type,
            "description": t.description, "icon": t.icon, "params_schema": t.params_schema,
            "content_template": t.content_template, "system_prompt": t.system_prompt,
            "writing_style": t.writing_style, "word_count": t.word_count,
            "need_red_header": t.need_red_header, "need_signature": t.need_signature,
            "need_date": t.need_date, "need_doc_number": t.need_doc_number,
            "is_builtin": t.is_builtin, "is_active": t.is_active, "use_count": t.use_count,
        }

    def create_template(self, user: User, req: TemplateCreateRequest) -> dict:
        visibility = req.visibility or "official"
        if visibility == "official" and user.role not in ADMIN_OR_ABOVE:
            raise PermissionDeniedError("官方模板仅管理员可创建，请选择'个人模板'")

        tmpl = WritingTemplate(
            name=req.name, category=req.category,
            base_type=req.base_type or "公文",
            description=req.description or "", icon=req.icon,
            params_schema=[p.model_dump() for p in req.params_schema],
            content_template=req.content_template,
            system_prompt=req.system_prompt or "",
            writing_style=req.writing_style or "正式公文",
            word_count=req.word_count or 1000,
            need_red_header=bool(req.need_red_header),
            need_signature=True if req.need_signature is None else req.need_signature,
            need_date=True if req.need_date is None else req.need_date,
            need_doc_number=bool(req.need_doc_number),
            keywords=req.keywords,
            is_builtin=False, is_active=True, created_by=user.id,
            sort_order=req.sort_order,
            template_kind=req.template_kind or "official_doc",
            tags=req.tags or [],
            scene=req.scene or "",
            writing_guide=req.writing_guide or "",
            structure=[s.model_dump() for s in (req.structure or [])],
            kb_ids=req.kb_ids or [],
            visibility=visibility,
            share_scope=req.share_scope or "all",
            share_departments=req.share_departments or [],
            share_roles=req.share_roles or [],
            is_draft=bool(req.is_draft),
        )
        # 写作参考模板：无固定结构，生成 content_template 兜底，写作要点并入 system_prompt
        if tmpl.template_kind == "writing_ref":
            if not tmpl.content_template:
                tmpl.content_template = req.writing_guide or req.description or "自由结构：AI 根据任务灵活组织文章"
            if req.writing_guide and req.writing_guide not in (tmpl.system_prompt or ""):
                tmpl.system_prompt = ((tmpl.system_prompt or "") + "\n写作要点与注意事项：" + req.writing_guide).strip()

        tmpl = self.templates.add(tmpl)
        return {"id": tmpl.id, "message": "Template created", "is_draft": tmpl.is_draft}

    def update_template(self, user: User, template_id: str, req: TemplateUpdateRequest) -> dict:
        tmpl = self.templates.get(template_id)
        if not tmpl:
            raise NotFoundError("Template not found")

        if tmpl.is_builtin and user.role != ROLE_DEVELOPER:
            raise PermissionDeniedError("Builtin templates can only be modified by system admin")
        is_owner_personal = (tmpl.visibility == "personal" and tmpl.created_by == user.id)
        if user.role not in ADMIN_OR_ABOVE and not is_owner_personal:
            raise PermissionDeniedError("无权修改该模板")

        simple_fields = ["name", "category", "description", "icon", "content_template",
                         "system_prompt", "is_active", "sort_order", "template_kind",
                         "tags", "scene", "kb_ids", "share_scope",
                         "share_departments", "share_roles", "is_draft"]
        for f in simple_fields:
            v = getattr(req, f, None)
            if v is not None:
                setattr(tmpl, f, v)

        if req.params_schema is not None:
            tmpl.params_schema = [p.model_dump() for p in req.params_schema]
        if req.structure is not None:
            tmpl.structure = [s.model_dump() for s in req.structure]
        if req.writing_guide is not None:
            tmpl.writing_guide = req.writing_guide
            if tmpl.template_kind == "writing_ref" \
                    and req.writing_guide not in (tmpl.system_prompt or ""):
                tmpl.system_prompt = ((tmpl.system_prompt or "") + "\n写作要点与注意事项：" + req.writing_guide).strip()
        if req.visibility is not None:
            if req.visibility == "official" and user.role not in ADMIN_OR_ABOVE:
                raise PermissionDeniedError("官方模板仅管理员可设置")
            tmpl.visibility = req.visibility

        self.templates.update(tmpl)
        return {"message": "Template updated"}

    def delete_template(self, user: User, template_id: str) -> dict:
        tmpl = self.templates.get(template_id)
        if not tmpl:
            raise NotFoundError("Template not found")
        if tmpl.is_builtin and user.role != ROLE_DEVELOPER:
            raise PermissionDeniedError("Builtin templates can only be deleted by system admin")
        self.templates.delete(tmpl)
        return {"message": "Template deleted"}

    def record_use(self, template_id: str) -> dict:
        self.templates.increment_use_count(template_id)
        return {"message": "Template use recorded"}
