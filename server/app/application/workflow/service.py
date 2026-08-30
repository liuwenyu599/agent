"""工作流应用服务：模板初始化、实例管理、上下文解析、节点 AI 生成。

上下文（workflow_context）统一存储在实例的 basic_info JSON 列中，
沿用旧系统约定（字段键 meeting_name 等标准键 + 自由键）。
"""
import json
import re
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.application.shared.writing_assistant import WritingAssistant
from app.application.workflow.builtin_data import (
    BUILTIN_WORKFLOWS,
    FIELD_LABEL_MAP,
    MEETING_STANDARD_FIELDS,
)
from app.core.exceptions import AppError, NotFoundError
from app.core.logging import get_logger
from app.domain.identity.entities import User
from app.domain.workflow.entities import (
    NodeInstance,
    WorkflowInstance,
    WorkflowNode,
    WorkflowTemplate,
)
from app.infrastructure.repositories.workflow import (
    SqlAlchemyNodeInstanceRepository,
    SqlAlchemyWorkflowInstanceRepository,
    SqlAlchemyWorkflowNodeRepository,
    SqlAlchemyWorkflowTemplateRepository,
)

logger = get_logger(__name__)


class WorkflowService:
    def __init__(self, db: Session, assistant: WritingAssistant) -> None:
        self.db = db
        self.assistant = assistant
        self.templates = SqlAlchemyWorkflowTemplateRepository(db)
        self.nodes = SqlAlchemyWorkflowNodeRepository(db)
        self.instances = SqlAlchemyWorkflowInstanceRepository(db)
        self.node_instances = SqlAlchemyNodeInstanceRepository(db)

    # ========== 模板 ==========
    def list_templates(self) -> dict:
        result = []
        for tpl in BUILTIN_WORKFLOWS:
            result.append({
                "id": tpl["code"],
                "code": tpl["code"],
                "name": tpl["name"],
                "category": tpl.get("category", "通用"),
                "description": tpl.get("description", ""),
                "nodes": [
                    {
                        "name": n["name"],
                        "stage": n.get("stage", ""),
                        "write_guide": n.get("write_guide", ""),
                        "sort_order": i,
                        "optional": n.get("optional", False),
                    }
                    for i, n in enumerate(tpl.get("nodes", []))
                ],
            })
        return {"templates": result}

    def _ensure_template_row(self, code: str) -> WorkflowTemplate:
        row = self.templates.get_by_code(code)
        if row:
            return row
        tpl = next((t for t in BUILTIN_WORKFLOWS if t["code"] == code), None)
        if not tpl:
            raise NotFoundError(f"未知模板: {code}")
        row = self.templates.add(WorkflowTemplate(
            name=tpl["name"], code=tpl["code"],
            category=tpl.get("category", "通用"),
            description=tpl.get("description", ""),
        ))
        for i, n in enumerate(tpl.get("nodes", [])):
            self.nodes.add(WorkflowNode(
                template_id=row.id, name=n["name"],
                stage=n.get("stage", ""), write_guide=n.get("write_guide", ""),
                sort_order=i, optional=n.get("optional", False),
            ))
        return row

    # ========== 实例 ==========
    def create_instance(self, user: User, template_code: str, title: str,
                        workflow_context: Dict[str, Any]) -> dict:
        tpl_row = self._ensure_template_row(template_code)
        inst = self.instances.add(WorkflowInstance(
            template_id=tpl_row.id, user_id=user.id, title=title,
            status="running", basic_info=workflow_context or {},
        ))
        nodes = self.nodes.list_by_template(tpl_row.id)
        for i, n in enumerate(nodes):
            self.node_instances.add(NodeInstance(
                instance_id=inst.id, node_id=n.id,
                sort_order=i, status="pending", content="",
            ))
        self.db.commit()
        return {"id": inst.id}

    def list_instances(self, user: User, status: Optional[str] = None) -> dict:
        insts = self.instances.list_by_user(user.id, status)
        return {"instances": [self._instance_to_dict(i) for i in insts]}

    def get_instance(self, inst_id: str) -> dict:
        return self._instance_to_dict(self._get_instance_checked(inst_id))

    def update_instance(self, inst_id: str, title: Optional[str], status: Optional[str],
                        basic_info: Optional[Dict[str, Any]],
                        workflow_context: Optional[Dict[str, Any]]) -> dict:
        inst = self._get_instance_checked(inst_id)
        if title is not None:
            inst.title = title
        if status is not None:
            inst.status = status
        if workflow_context is not None:
            inst.basic_info = workflow_context
        elif basic_info is not None:
            inst.basic_info = self._migrate_basic_info_to_context(basic_info)
        self.instances.update(inst)
        self.db.commit()
        return {"ok": True}

    def delete_instance(self, inst_id: str) -> dict:
        inst = self._get_instance_checked(inst_id)
        self.node_instances.delete_by_instance(inst.id)
        self.instances.delete(inst)
        self.db.commit()
        return {"ok": True}

    def _get_instance_checked(self, inst_id: str) -> WorkflowInstance:
        inst = self.instances.get(inst_id)
        if not inst:
            raise NotFoundError("工作流不存在")
        return inst

    # ========== 上下文解析 ==========
    def parse_natural_language(self, inst_id: str, text: str) -> dict:
        self._get_instance_checked(inst_id)
        prompt = f"""你是司法行政机关的公文信息提取助手。用户会用口语描述一场会议，请提取结构化信息，
并把口语表述【规范化】为正式公文语言，严格按 JSON 格式输出。

可识别的标准字段：
- meeting_name: 会议名称（规范全称，如"2026年上半年司法行政工作总结会议"，不要用"总结会""碰头会"等口头叫法）
- meeting_time: 会议时间（保留原文时间信息，表述规范化，如"下周三上午"→"2026年8月26日（周三）上午"，无法确定具体日期时保留"下周"等原表述）
- meeting_location: 会议地点
- organizer: 主办单位/部门（规范全称，如"局办公室""普法与依法治理科"）
- host: 主持人
- participants: 参会人员（规范表述，如"局领导班子成员、各科室负责人"，不要"局领导都来吧"这类口语）
- purpose: 会议目的（用"总结……，分析……，研究部署……"式规范句式，一句完整的话）
- topic: 会议主题（凝练的规范短语，如"上半年工作总结与下一阶段工作部署"）

输入描述（口语原文）：
{text}

要求：
1. 只输出合法 JSON，不要任何解释、markdown 代码块标记或对话口吻；
2. 提取后必须将口语转化为体制内规范表述，禁止照搬口语词汇（如"看看""干得怎么样""聊一聊"）；
3. 未提取到的字段不要输出，或输出 null；不得虚构人名、日期、部门名称；
4. 描述中"总结上半年工作并部署下半年任务"这类内容，归入 purpose 或 topic，并用规范句式表达。

JSON："""
        try:
            raw = self.assistant.complete(
                [{"role": "user", "content": prompt}],
                temperature=0.1, max_tokens=800,
            )
            raw = re.sub(r'^```json\s*', '', raw.strip())
            raw = re.sub(r'\s*```$', '', raw.strip())
            parsed = json.loads(raw)
            parsed = {k: v for k, v in parsed.items() if v is not None and str(v).strip()}
        except Exception as e:
            logger.exception("自然语言解析失败")
            raise AppError(500, f"解析失败: {e}")
        return {"parsed": parsed}

    def parse_key_value(self, inst_id: str, text: str) -> dict:
        inst = self._get_instance_checked(inst_id)
        current_ctx = self._get_workflow_context(inst)
        parsed = {}
        for line in text.split('\n'):
            line = line.strip()
            if not line:
                continue
            if '：' in line:
                parts = line.split('：', 1)
            elif ':' in line:
                parts = line.split(':', 1)
            else:
                continue
            key = parts[0].strip()
            val = parts[1].strip() if len(parts) > 1 else ""
            if key and val:
                mapped_key = None
                for std, labels in {
                    "meeting_name": ["会议名称"],
                    "meeting_time": ["会议时间", "时间"],
                    "meeting_location": ["会议地点", "地点"],
                    "organizer": ["主办单位", "主办部门", "组织者", "负责"],
                    "host": ["主持人", "主持"],
                    "participants": ["参会人员", "参会范围", "参加人员", "人员"],
                    "purpose": ["会议目的", "目的"],
                    "topic": ["会议主题", "主题"],
                }.items():
                    if key in labels:
                        mapped_key = std
                        break
                parsed[mapped_key or key] = val
        conflicts = []
        for key, new_val in parsed.items():
            old_val = current_ctx.get(key)
            if old_val and str(old_val).strip() and str(old_val).strip() != str(new_val).strip():
                conflicts.append({
                    "field": key,
                    "label": FIELD_LABEL_MAP.get(key, key),
                    "old_value": old_val,
                    "new_value": new_val,
                })
        return {
            "parsed": parsed,
            "conflicts": conflicts,
            "has_conflict": len(conflicts) > 0,
        }

    def confirm_context(self, inst_id: str, workflow_context: Dict[str, Any],
                        confirm_overrides: Dict[str, bool]) -> dict:
        inst = self._get_instance_checked(inst_id)
        current_ctx = self._get_workflow_context(inst)
        new_ctx = dict(current_ctx)
        for key, val in workflow_context.items():
            if key in current_ctx and current_ctx[key] != val:
                if not (confirm_overrides or {}).get(key, False):
                    continue
            new_ctx[key] = val
        inst.basic_info = new_ctx
        self.instances.update(inst)
        self.db.commit()
        return {"ok": True, "workflow_context": new_ctx}

    # ========== 节点 ==========
    def update_node(self, node_inst_id: str, content: Optional[str],
                    status: Optional[str]) -> dict:
        ni = self._get_node_instance_checked(node_inst_id)
        if content is not None:
            ni.content = content
            if ni.status == "pending":
                ni.status = "draft"
        if status is not None:
            ni.status = status
        self.node_instances.update(ni)
        self.db.commit()
        return {"ok": True, "status": ni.status}

    def generate_node(self, node_inst_id: str, instruction: str = "",
                      save: bool = True) -> dict:
        ni = self._get_node_instance_checked(node_inst_id)
        node = self.nodes.get(ni.node_id)
        inst = self.instances.get(ni.instance_id)
        if not node or not inst:
            raise NotFoundError("数据不完整")
        ctx = self._get_workflow_context(inst)
        ctx_text = self._build_context_text(ctx)
        upstream_items = self._get_upstream_contents(inst, ni)
        if upstream_items:
            upstream_text = "\n\n".join(
                f"【{item['name']}】\n{item['content']}" for item in upstream_items
            )
        else:
            upstream_text = "（暂无）"
        is_table_node = any(k in node.name for k in ("签到", "名单", "清单", "分工"))
        table_req = ""
        if is_table_node:
            table_req = """
【表格输出要求】
本节点为表格类材料，请严格按以下格式输出：
1. 每行一条记录，字段之间用制表符（Tab）分隔；不输出表头行，不输出任何说明性文字；
2. 签到表字段顺序固定为：序号、姓名、单位、职务、联系电话、签到（签到列留空）；
3. 名单优先取基础信息中的参会人员；基础信息未明确姓名时，按参会范围生成相应数量的"××"占位行；
4. 禁止 markdown 表格符号（|），禁止对话口吻。"""
        dependency_note = ""
        if "主持稿" in node.name:
            dependency_note = "\n【数据依赖】本节点需要结合「会议议程」内容撰写主持串联词。"
        elif "会议纪要" in node.name:
            dependency_note = "\n【数据依赖】本节点需要结合「会议材料」提炼议定事项和工作要求。"
        elif "简报" in node.name or "新闻稿" in node.name:
            dependency_note = "\n【数据依赖】本节点需要结合「会议纪要」和「会议材料」提炼宣传要点。"
        prompt = f"""你是司法行政机关的公文写作助手。请为以下工作流节点撰写内容。

【工作流】{inst.title}
【当前节点】{node.name}（{node.stage}）
【写作要求】{node.write_guide or '内容规范、详实、可直接使用'}
{dependency_note}

【会议基本信息】（唯一权威数据源）
{ctx_text}

【前序节点已完成内容（按数据依赖关系带入）】
{upstream_text}

【用户补充要求】
{instruction or '无'}
{table_req}
写作纪律：
1. 直接输出正文，禁止"当然/好的/以下是"等对话口吻；
2. 禁止使用 markdown 符号（#、*、-、|），层级用"一、（一）、1."中文序号；
3. 禁止只列提纲，正文须为完整段落；
4. 不得虚构人名、数据，无依据处用"××"占位；
5. 公文类内容遵循 GB/T 9704-2012 格式表述习惯；
6. 基础信息中若残留口语化表述（如"总结会""聊一聊"），生成正文时必须转化为规范公文语言。"""
        try:
            content = self.assistant.complete(
                [{"role": "user", "content": prompt}],
                temperature=0.5, max_tokens=3000,
            )
        except Exception as e:
            logger.exception("节点生成失败")
            raise AppError(500, f"生成失败: {e}")
        if save:
            ni.content = content
            if ni.status == "pending":
                ni.status = "draft"
            self.node_instances.update(ni)
            self.db.commit()
        return {"content": content, "status": ni.status, "saved": save}

    def _get_node_instance_checked(self, node_inst_id: str) -> NodeInstance:
        ni = self.node_instances.get(node_inst_id)
        if not ni:
            raise NotFoundError("节点不存在")
        return ni

    # ========== 内部辅助 ==========
    @staticmethod
    def _get_workflow_context(inst: WorkflowInstance) -> Dict[str, Any]:
        ctx = inst.basic_info
        if isinstance(ctx, str):
            try:
                ctx = json.loads(ctx)
            except Exception:
                ctx = {}
        return ctx or {}

    @staticmethod
    def _migrate_basic_info_to_context(basic: Dict[str, Any]) -> Dict[str, Any]:
        mapping = {
            "会议名称": "meeting_name", "会议时间": "meeting_time", "时间": "meeting_time",
            "会议地点": "meeting_location", "地点": "meeting_location",
            "主办单位": "organizer", "主办部门": "organizer", "组织者": "organizer", "负责": "organizer",
            "主持人": "host", "主持": "host",
            "参会人员": "participants", "参会范围": "participants", "参加人员": "participants", "人员": "participants",
            "会议目的": "purpose", "目的": "purpose",
            "会议主题": "topic", "主题": "topic",
        }
        ctx = {}
        for k, v in basic.items():
            key = mapping.get(k.strip(), k.strip())
            ctx[key] = v
        return ctx

    @staticmethod
    def _build_context_text(ctx: Dict[str, Any]) -> str:
        lines = []
        for field in MEETING_STANDARD_FIELDS:
            label = FIELD_LABEL_MAP.get(field, field)
            val = ctx.get(field)
            if val:
                lines.append(f"{label}：{val}")
        for k, v in ctx.items():
            if k not in MEETING_STANDARD_FIELDS and v:
                lines.append(f"{k}：{v}")
        return "\n".join(lines) if lines else "（未填写）"

    def _get_upstream_contents(self, inst: WorkflowInstance,
                               current_ni: NodeInstance) -> List[Dict[str, str]]:
        upstream = self.node_instances.list_upstream(inst.id, current_ni.sort_order)
        node_map = {nd.id: nd for nd in self.nodes.list_by_ids([u.node_id for u in upstream])}
        current = node_map.get(current_ni.node_id) or self.nodes.get(current_ni.node_id)
        current_name = current.name if current else ""
        dependency_rules = {
            "主持稿": ["会议议程"],
            "会议纪要": ["会议材料"],
            "简报/新闻稿": ["会议纪要", "会议材料"],
            "归档": ["会议通知", "会议议程", "会议纪要", "简报/新闻稿"],
        }
        required_names = dependency_rules.get(current_name, [])
        result = []
        for u in upstream:
            if not u.content or not u.content.strip():
                continue
            nd = node_map.get(u.node_id)
            name = nd.name if nd else ""
            if "基础信息" in name:
                continue
            if required_names and name not in required_names:
                continue
            result.append({"name": name, "content": u.content.strip()[:2000]})
        if not required_names:
            result = []
            for u in upstream:
                if not u.content or not u.content.strip():
                    continue
                nd = node_map.get(u.node_id)
                name = nd.name if nd else ""
                if "基础信息" in name:
                    continue
                result.append({"name": name, "content": u.content.strip()[:1500]})
        return result

    def _node_to_dict(self, ni: NodeInstance, node: Optional[WorkflowNode]) -> Dict[str, Any]:
        return {
            "id": ni.id,
            "node_id": ni.node_id,
            "name": node.name if node else "",
            "stage": node.stage if node else "",
            "write_guide": node.write_guide if node else "",
            "sort_order": ni.sort_order,
            "optional": node.optional if node else False,
            "status": ni.status,
            "content": ni.content or "",
            "updated_at": ni.updated_at.strftime("%m-%d %H:%M") if ni.updated_at else "",
        }

    def _instance_to_dict(self, inst: WorkflowInstance) -> Dict[str, Any]:
        tpl = self.templates.get(inst.template_id)
        node_insts = self.node_instances.list_by_instance(inst.id)
        node_map = {nd.id: nd for nd in self.nodes.list_by_ids([ni.node_id for ni in node_insts])}
        ctx = self._get_workflow_context(inst)
        return {
            "id": inst.id,
            "title": inst.title,
            "status": inst.status,
            "template_id": inst.template_id,
            "template_code": tpl.code if tpl else "",
            "template_name": tpl.name if tpl else "",
            "workflow_context": ctx,
            "basic_info": ctx,
            "created_at": inst.created_at.strftime("%Y-%m-%d %H:%M") if inst.created_at else "",
            "creator": "",
            "nodes": [self._node_to_dict(ni, node_map.get(ni.node_id)) for ni in node_insts],
        }
