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
from app.core.logging import get_logger
from app.domain.identity.entities import ADMIN_OR_ABOVE, ROLE_DEVELOPER, User
from app.domain.templates.entities import TemplateCategory, WritingTemplate
from app.infrastructure.repositories.templates import (
    SqlAlchemyTemplateCategoryRepository,
    SqlAlchemyWritingTemplateRepository,
)

logger = get_logger(__name__)


def _body_skeleton_from_content(content: str) -> list:
    """Convert the existing built-in body outline into ordered preview entries."""
    lines = [line.strip() for line in (content or "").splitlines() if line.strip()]
    result = []
    for line in lines:
        if line.startswith("正文骨架："):
            line = line.removeprefix("正文骨架：").strip()
        if line:
            result.append({"name": line[:120], "guide": ""})
    return result


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
                existing.structure = t.get("structure", [])
                existing.body_skeleton = (t.get("body_skeleton") or t.get("structure")
                                          or _body_skeleton_from_content(t.get("content_template", "")))
                existing.format_profile = t.get("format_profile", "GBT_RULES")
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
                structure=t.get("structure", []),
                body_skeleton=(t.get("body_skeleton") or t.get("structure")
                               or _body_skeleton_from_content(t.get("content_template", ""))),
                format_profile=t.get("format_profile", "GBT_RULES"),
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
        """模板三层：系统模板 / 本科室模板 / 我的模板。

        归属完全由服务端判定：department_code 由登录用户解析，不接受客户端入参。
        排序：本科室模板优先，其后系统模板，最后我的模板。
        """
        dept_code = self._dept_code_of(user)
        rows = self.templates.list_active(category)
        visible = []
        for t in rows:
            if t.visible_to(user.id, user.role, user.department):
                visible.append(t)
            elif dept_code and (t.department_code or "") == dept_code:
                visible.append(t)
        ranked = sorted(visible, key=lambda t: self._tier_rank(t, dept_code, user.id))
        return [self._to_list_dict(t, dept_code, user.id) for t in ranked]

    @staticmethod
    def _tier_of(t: WritingTemplate, dept_code: str, user_id: str) -> str:
        """归属判定：

        - department：显式归属本科室（department_code 匹配）；
        - mine：个人模板（visibility=personal 且本人创建）；
        - system：其余一律为系统模板（含内置 / 官方模板，即使是本人创建）。
        """
        if (t.department_code or "") and dept_code and t.department_code == dept_code:
            return "department"
        if (t.visibility or "") == "personal" and t.created_by and t.created_by == user_id:
            return "mine"
        return "system"

    @classmethod
    def _tier_rank(cls, t: WritingTemplate, dept_code: str, user_id: str) -> int:
        return {"department": 0, "system": 1, "mine": 2}[cls._tier_of(t, dept_code, user_id)]

    def _to_list_dict(self, t: WritingTemplate, dept_code: str = "",
                      user_id: str = "") -> dict:
        tier = self._tier_of(t, dept_code, user_id)
        return {
            "id": t.id, "name": t.name, "category": t.category, "base_type": t.base_type,
            "department_code": t.department_code or "", "tier": tier,
            "description": t.description, "icon": t.icon, "params_schema": t.params_schema,
            "content_template": t.content_template, "system_prompt": t.system_prompt,
            "is_builtin": t.is_builtin, "use_count": t.use_count,
            "writing_style": t.writing_style, "word_count": t.word_count,
            "need_red_header": t.need_red_header, "need_signature": t.need_signature,
            "need_date": t.need_date, "need_doc_number": t.need_doc_number,
            "keywords": t.keywords,
            "template_kind": t.template_kind, "tags": t.tags or [],
            "scene": t.scene or "", "writing_guide": t.writing_guide or "",
            "structure": t.structure or [], "kb_ids": t.kb_ids or [],
            "body_skeleton": t.body_skeleton or [], "format_profile": t.format_profile or "GBT_RULES",
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
            "template_kind": t.template_kind, "tags": t.tags or [],
            "scene": t.scene or "", "writing_guide": t.writing_guide or "",
            "structure": t.structure or [], "kb_ids": t.kb_ids or [],
            "body_skeleton": t.body_skeleton or [], "format_profile": t.format_profile or "GBT_RULES",
            "visibility": t.visibility, "share_scope": t.share_scope,
            "share_departments": t.share_departments or [],
            "share_roles": t.share_roles or [],
            "is_draft": bool(t.is_draft),
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
            body_skeleton=[s.model_dump() for s in (req.body_skeleton or [])]
            or [s.model_dump() for s in (req.structure or [])],
            format_profile=req.format_profile or "GBT_RULES",
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
        if req.body_skeleton is not None:
            tmpl.body_skeleton = [s.model_dump() for s in req.body_skeleton]
        if req.format_profile is not None:
            tmpl.format_profile = req.format_profile
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

    # ---- 科室模板：AI 按本科室写作习惯调整，人工确认后保存 ----

    def _dept_code_of(self, user: User) -> str:
        """当前登录用户的科室 code：由服务端从 users 表解析，不接受客户端入参。"""
        from sqlalchemy import select as _select

        from app.application.organization.service import OrganizationService
        from app.infrastructure.database.models.identity import UserModel

        row = self.db.scalar(_select(UserModel).where(UserModel.id == user.id))
        if row is None:
            return ""
        return OrganizationService(self.db)._effective_code(row)

    def adapt_for_department(self, user: User, template_id: str,
                             hints: str = "") -> dict:
        """基于现有模板生成调整草案：只做建议，不落库，等人工确认。

        权限：任何登录用户都可生成草案（草案本身不落库、不影响任何数据）；
        落库环节另有限制——科室管理员保存为科室模板（save_department_template），
        普通用户保存为个人模板（create_template + visibility=personal）。
        LLM 不可用时降级为规则化改写，并在 source 标注 rule，前端据此提示"已按规则生成，请人工校核"。
        """
        src = self.templates.get(template_id)
        if not src:
            raise NotFoundError("Template not found")

        dept_code = self._dept_code_of(user)
        if not dept_code:
            raise PermissionDeniedError("当前账号未归属科室，无法生成调整草案")

        org = None
        try:
            from app.application.organization.service import OrganizationService
            org_svc = OrganizationService(self.db)
            org = org_svc._raw_agent(dept_code)
        except Exception:
            org = None

        dept_name = (org or {}).get("dept_name") or dept_code
        base_content = src.content_template or ""
        base_guide = src.writing_guide or src.description or ""
        biz = (org or {}).get("business_prompt") or ""
        req = (org or {}).get("work_requirements") or ""

        prompt = (
            "你是司法行政机关的公文模板编写助手。请把下面这份通用模板，"
            f"改写为「{dept_name}」日常使用的模板。\n\n"
            "要求：\n"
            "1. 保持公文法定结构与规范用语，不编造制度、数据与文号；\n"
            "2. 章节顺序贴合该科室实际写作习惯；\n"
            "3. 输出纯文本模板正文，用【】标注需要填写的占位要素；\n"
            "4. 不要输出解释性说明。\n\n"
            f"【本科室业务特点】\n{biz}\n\n"
            f"【本科室工作要求】\n{req}\n\n"
            f"【调整重点】\n{hints or '按本科室常见场景优化章节与表述'}\n\n"
            f"【原模板名称】{src.name}\n"
            f"【原模板正文】\n{base_content[:4000]}\n"
            f"【原写作要点】\n{base_guide[:1000]}\n"
        )

        content, source = "", "rule"
        try:
            from app.infrastructure.ai import get_llm_gateway
            gateway = get_llm_gateway()
            if gateway is not None:
                content = (gateway.complete(
                    [{"role": "user", "content": prompt}],
                    temperature=0.5, max_tokens=4096,
                ) or "").strip()
                source = "llm"
        except Exception as e:
            logger.warning("[模板] 本科室化改写不可用，降级为规则生成: %s", e)
        if not content:
            content = self._rule_adapt(src, dept_name, hints)
            source = "rule"

        return {
            "source_template_id": src.id,
            "source_template_name": src.name,
            "dept_code": dept_code,
            "dept_name": dept_name,
            "name": f"{src.name}（{dept_name}）",
            "category": src.category,
            "base_type": src.base_type,
            "description": f"基于「{src.name}」按{dept_name}写作习惯调整",
            "content_template": content,
            "writing_guide": base_guide,
            "writing_style": src.writing_style,
            "word_count": src.word_count,
            "need_red_header": src.need_red_header,
            "need_signature": src.need_signature,
            "need_date": src.need_date,
            "need_doc_number": src.need_doc_number,
            "params_schema": src.params_schema or [],
            "structure": src.structure or [],
            "body_skeleton": src.body_skeleton or [],
            "format_profile": src.format_profile or "GBT_RULES",
            "system_prompt": src.system_prompt or "",
            "template_kind": src.template_kind,
            "tags": src.tags or [],
            "source": source,
        }

    @staticmethod
    def _rule_adapt(src, dept_name: str, hints: str) -> str:
        """LLM 不可用时的规则化改写：保留原结构，补本科室口径说明。"""
        head = [f"【{dept_name}专用】{src.name}",
                "",
                f"编写口径：{hints or '按本科室常用表述与章节顺序撰写'}。",
                "填写说明：带【】的部分为需补充的要素，请勿留空。",
                ""]
        return "\n".join(head) + (src.content_template or "")

    def _inherit_from_source(self, body: dict) -> dict:
        """要素缺失时从源模板继承填写要素与写作配置（防御性兜底）。

        触发条件：``params_schema`` 为空（前端漏传字段 / 旧客户端调用）且请求带了
        ``source_template_id``。命中后把源模板的 ``params_schema``、``structure``、
        ``system_prompt``、``writing_guide``、``writing_style``、``word_count`` 与
        ``need_*`` 标志一并继承过来，避免落库出「无需填写要素」的空模板。

        源模板取不到（ID 不存在 / 已被删除 / 查询异常）时原样返回，不抛异常。

        Args:
            body: 客户端提交的请求体，不会被就地修改。

        Returns:
            补全后的新 dict；无需继承时返回原 ``body``。
        """
        if body.get("params_schema"):
            return body
        source_id = str(body.get("source_template_id") or "").strip()
        if not source_id:
            return body
        try:
            src = self.templates.get(source_id)
        except Exception as e:  # 源模板查询异常不应阻断保存
            logger.warning("[模板] 源模板读取失败，跳过要素继承: %s", e)
            return body
        if not src:
            logger.warning("[模板] 源模板不存在(%s)，跳过要素继承", source_id)
            return body

        merged = dict(body)
        merged.update({
            "params_schema": getattr(src, "params_schema", None) or [],
            "structure": getattr(src, "structure", None) or [],
            "body_skeleton": getattr(src, "body_skeleton", None) or [],
            "format_profile": getattr(src, "format_profile", None) or "GBT_RULES",
            "system_prompt": getattr(src, "system_prompt", None) or "",
            "writing_guide": getattr(src, "writing_guide", None) or "",
            "writing_style": getattr(src, "writing_style", None) or "正式公文",
            "word_count": getattr(src, "word_count", None) or 1000,
            "need_red_header": bool(getattr(src, "need_red_header", False)),
            "need_signature": bool(getattr(src, "need_signature", True)),
            "need_date": bool(getattr(src, "need_date", True)),
            "need_doc_number": bool(getattr(src, "need_doc_number", False)),
        })
        logger.info("[模板] 科室模板要素为空，已从源模板 %s 继承 %d 项要素",
                    source_id, len(merged["params_schema"]))
        return merged

    def save_department_template(self, user: User, body: dict) -> dict:
        """人工确认后保存为本科室模板（服务端强制写入本人所属科室）。"""
        role = getattr(user, "role", "") or ""
        if role not in ADMIN_OR_ABOVE:
            raise PermissionDeniedError("仅科室管理员可保存本科室模板")
        dept_code = self._dept_code_of(user)
        if not dept_code:
            raise PermissionDeniedError("当前账号未归属科室，无法保存科室模板")

        body = self._inherit_from_source(body)

        name = str(body.get("name") or "").strip()
        content = str(body.get("content_template") or "").strip()
        if not name:
            raise AppError(400, "模板名称不能为空")
        if not content:
            raise AppError(400, "模板正文不能为空")

        tmpl = WritingTemplate(
            name=name[:100],
            category=str(body.get("category") or "科室模板")[:50],
            department_code=dept_code,
            base_type=str(body.get("base_type") or "公文")[:50],
            description=str(body.get("description") or ""),
            icon="Document",
            params_schema=body.get("params_schema") or [],
            content_template=content,
            system_prompt=str(body.get("system_prompt") or ""),
            writing_style=str(body.get("writing_style") or "正式公文")[:50],
            word_count=int(body.get("word_count") or 1000),
            need_red_header=bool(body.get("need_red_header")),
            need_signature=body.get("need_signature", True) is not False,
            need_date=body.get("need_date", True) is not False,
            need_doc_number=bool(body.get("need_doc_number")),
            is_builtin=False, is_active=True, created_by=user.id,
            template_kind=str(body.get("template_kind") or "official_doc"),
            tags=body.get("tags") or [],
            scene=str(body.get("scene") or ""),
            writing_guide=str(body.get("writing_guide") or ""),
            structure=body.get("structure") or [],
            body_skeleton=body.get("body_skeleton") or body.get("structure") or [],
            format_profile=body.get("format_profile") or "GBT_RULES",
            visibility="department",
        )
        tmpl = self.templates.add(tmpl)
        try:
            from app.application.audit.service import AuditService
            AuditService.from_db(self.db).log(
                action="template_dept_save", resource_type="template",
                resource_id=tmpl.id,
                detail={"dept_code": dept_code, "name": tmpl.name,
                        "source_template_id": body.get("source_template_id") or ""},
                result="success",
            )
        except Exception:
            pass
        return {"id": tmpl.id, "message": "科室模板已保存",
                "department_code": dept_code}

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
