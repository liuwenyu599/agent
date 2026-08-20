# -*- coding: utf-8 -*-
"""
工作流 API —— 完整文件，直接覆盖 backend/api/workflow.py

说明：WorkflowInstance 模型只有 basic_info（JSON）列，没有 workflow_context 列。
本文件把"会议核心上下文"统一存储在 basic_info 中（字段键沿用 meeting_name 等
标准键 + 自由键），前端无需改动。接口保持不变：parse-natural-language /
parse-key-value / confirm-context / nodes/{id}/generate 全部可用。
"""
import json
import logging
import re
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from backend.database.postgres import get_db
from backend.database.models import (
    WorkflowTemplate, WorkflowNode, WorkflowInstance, NodeInstance,
)
from backend.api.auth import get_current_user
from backend.services.llm_service import LLMService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/workflow", tags=["workflow"])
llm_service = LLMService()

BUILTIN_WORKFLOWS: List[Dict[str, Any]] = [
    {
        "code": "meeting", "name": "会议组织", "category": "综合",
        "description": "会议全流程：基础信息、通知、议程、签到、主持稿、纪要、简报、归档",
        "nodes": [
            {"name": "基础信息", "stage": "会前", "write_guide": "维护会议结构化信息：名称、时间、地点、主题、主办部门、参会范围等。此节点不生成独立文本，直接编辑工作流核心数据。"},
            {"name": "会议通知", "stage": "会前", "write_guide": "起草正式会议通知：会议时间地点、参会人员、会议内容、有关要求，符合公文格式。"},
            {"name": "参会人员", "stage": "会前", "write_guide": "整理参会人员名单：姓名、单位、职务，分组排列。"},
            {"name": "会议议程", "stage": "会前", "write_guide": "生成会议详细议程安排：各环节内容、时间、主持人、发言人。"},
            {"name": "签到表", "stage": "会中", "write_guide": "生成签到表：序号、姓名、单位、职务、联系电话、签到栏。"},
            {"name": "主持稿", "stage": "会中", "write_guide": "起草会议主持稿：开场白、议程串联词、结束语，符合领导讲话习惯。"},
            {"name": "会议材料", "stage": "会中", "write_guide": "整理会上印发/汇报使用的会议材料。"},
            {"name": "会议纪要", "stage": "会后", "write_guide": "起草会议纪要：会议基本情况、议定事项、工作要求，符合纪要规范。"},
            {"name": "简报/新闻稿", "stage": "会后", "write_guide": "撰写会议简报或新闻稿，用于政务公开和宣传报道。"},
            {"name": "归档", "stage": "会后", "write_guide": "汇总归档清单：通知、议程、签到表、纪要、简报等材料目录。"},
        ],
    },
    {
        "code": "activity", "name": "活动组织", "category": "综合",
        "description": "活动方案、通知、物料、分工、执行、总结、宣传全流程",
        "nodes": [
            {"name": "基础信息", "stage": "前期", "write_guide": "汇总活动名称、时间、地点、主题、主办单位、参与对象。"},
            {"name": "活动方案", "stage": "前期", "write_guide": "起草活动方案：目的意义、时间地点、内容安排、组织分工、保障措施。"},
            {"name": "活动通知", "stage": "前期", "write_guide": "起草活动通知，符合公文格式。"},
            {"name": "物料清单", "stage": "中期", "write_guide": "列出活动所需物料、数量、责任人。"},
            {"name": "人员分工", "stage": "中期", "write_guide": "明确各工作组及人员职责分工。"},
            {"name": "现场执行记录", "stage": "中期", "write_guide": "记录活动实施过程、到场情况、突发事项处理。"},
            {"name": "活动总结", "stage": "后期", "write_guide": "撰写活动总结：开展情况、取得成效、经验不足、下一步打算。"},
            {"name": "宣传简报", "stage": "后期", "write_guide": "撰写活动宣传简报/新闻稿。"},
        ],
    },
    {
        "code": "research", "name": "调研工作", "category": "业务",
        "description": "调研方案、提纲、记录、分析、报告、成果转化",
        "nodes": [
            {"name": "基础信息", "stage": "前期", "write_guide": "汇总调研课题、时间、地点、参加人员、调研对象。"},
            {"name": "调研方案", "stage": "前期", "write_guide": "起草调研方案：背景目的、内容方式、日程安排、工作要求。"},
            {"name": "调研提纲", "stage": "前期", "write_guide": "列出调研访谈提纲和重点问题清单。"},
            {"name": "调研记录", "stage": "中期", "write_guide": "整理调研过程记录、座谈要点、实地走访情况。"},
            {"name": "数据分析", "stage": "中期", "write_guide": "汇总分析调研数据和反映的主要问题。"},
            {"name": "调研报告", "stage": "后期", "write_guide": "起草调研报告：基本情况、存在问题、原因分析、对策建议。"},
            {"name": "成果转化建议", "stage": "后期", "write_guide": "提出调研成果转化运用的具体建议。"},
        ],
    },
    {
        "code": "report", "name": "汇报材料", "category": "业务",
        "description": "汇报提纲、初稿、修改稿、定稿、PPT 要点",
        "nodes": [
            {"name": "基础信息", "stage": "准备", "write_guide": "汇总汇报主题、汇报对象、汇报人、时间场合、时长要求。"},
            {"name": "汇报提纲", "stage": "准备", "write_guide": "搭建汇报提纲：总体框架、各部分要点。"},
            {"name": "初稿撰写", "stage": "起草", "write_guide": "按提纲撰写汇报材料初稿，内容详实、数据准确。"},
            {"name": "修改完善", "stage": "起草", "write_guide": "根据反馈修改完善，突出亮点、精炼文字。"},
            {"name": "定稿审核", "stage": "审核", "write_guide": "定稿送审版，格式规范、表述严谨。"},
            {"name": "PPT要点", "stage": "审核", "write_guide": "提炼汇报 PPT 要点：每页标题、核心内容、数据图表建议。"},
        ],
    },
]

class CreateInstanceRequest(BaseModel):
    template_code: str
    title: str
    workflow_context: Dict[str, Any] = Field(default_factory=dict)

class UpdateInstanceRequest(BaseModel):
    title: Optional[str] = None
    status: Optional[str] = None
    basic_info: Optional[Dict[str, Any]] = None
    workflow_context: Optional[Dict[str, Any]] = None

class UpdateNodeRequest(BaseModel):
    content: Optional[str] = None
    status: Optional[str] = None

class GenerateNodeRequest(BaseModel):
    instruction: str = ""
    save: bool = True

class ParseNaturalLanguageRequest(BaseModel):
    text: str

class ParseKeyValueRequest(BaseModel):
    text: str

class ConfirmContextRequest(BaseModel):
    workflow_context: Dict[str, Any]
    confirm_overrides: Optional[Dict[str, bool]] = Field(default_factory=dict)

MEETING_STANDARD_FIELDS = [
    "meeting_name", "meeting_time", "meeting_location",
    "organizer", "host", "participants", "purpose", "topic"
]

FIELD_LABEL_MAP = {
    "meeting_name": "会议名称",
    "meeting_time": "会议时间",
    "meeting_location": "会议地点",
    "organizer": "主办单位",
    "host": "主持人",
    "participants": "参会人员",
    "purpose": "会议目的",
    "topic": "会议主题",
}

def _ensure_template_row(db: Session, code: str) -> WorkflowTemplate:
    row = db.query(WorkflowTemplate).filter(WorkflowTemplate.code == code).first()
    if row:
        return row
    tpl = next((t for t in BUILTIN_WORKFLOWS if t["code"] == code), None)
    if not tpl:
        raise HTTPException(status_code=404, detail=f"未知模板: {code}")
    row = WorkflowTemplate(
        name=tpl["name"], code=tpl["code"],
        category=tpl.get("category", "通用"),
        description=tpl.get("description", ""),
    )
    db.add(row)
    db.flush()
    for i, n in enumerate(tpl.get("nodes", [])):
        db.add(WorkflowNode(
            template_id=row.id, name=n["name"],
            stage=n.get("stage", ""), write_guide=n.get("write_guide", ""),
            sort_order=i, optional=n.get("optional", False),
        ))
    db.flush()
    return row

def _node_to_dict(ni: NodeInstance, node: Optional[WorkflowNode]) -> Dict[str, Any]:
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
        "updated_at": ni.updated_at.strftime("%m-%d %H:%M") if getattr(ni, "updated_at", None) else "",
    }

def _get_workflow_context(inst: WorkflowInstance) -> Dict[str, Any]:
    """读取实例核心上下文（存于 basic_info 列，模型无 workflow_context 字段）。"""
    ctx = getattr(inst, "basic_info", None)
    if isinstance(ctx, str):
        try:
            ctx = json.loads(ctx)
        except Exception:
            ctx = {}
    return ctx or {}

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

def _instance_to_dict(db: Session, inst: WorkflowInstance) -> Dict[str, Any]:
    tpl = db.query(WorkflowTemplate).filter(WorkflowTemplate.id == inst.template_id).first()
    node_insts = (
        db.query(NodeInstance)
        .filter(NodeInstance.instance_id == inst.id)
        .order_by(NodeInstance.sort_order)
        .all()
    )
    node_ids = [ni.node_id for ni in node_insts]
    node_map = {}
    if node_ids:
        for nd in db.query(WorkflowNode).filter(WorkflowNode.id.in_(node_ids)).all():
            node_map[nd.id] = nd
    ctx = _get_workflow_context(inst)
    return {
        "id": inst.id,
        "title": inst.title,
        "status": inst.status,
        "template_id": inst.template_id,
        "template_code": tpl.code if tpl else "",
        "template_name": tpl.name if tpl else "",
        "workflow_context": ctx,
        "basic_info": ctx,
        "created_at": inst.created_at.strftime("%Y-%m-%d %H:%M") if getattr(inst, "created_at", None) else "",
        "creator": getattr(inst, "creator_name", "") or "",
        "nodes": [_node_to_dict(ni, node_map.get(ni.node_id)) for ni in node_insts],
    }

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

def _get_upstream_contents(db: Session, inst: WorkflowInstance, current_ni: NodeInstance) -> List[Dict[str, str]]:
    upstream = (
        db.query(NodeInstance)
        .filter(NodeInstance.instance_id == inst.id,
                NodeInstance.sort_order < current_ni.sort_order)
        .order_by(NodeInstance.sort_order)
        .all()
    )
    node_ids = [u.node_id for u in upstream]
    node_map = {nd.id: nd for nd in db.query(WorkflowNode).filter(WorkflowNode.id.in_(node_ids)).all()} if node_ids else {}
    current_name = node_map.get(current_ni.node_id)
    current_name = current_name.name if current_name else ""
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
        name = node_map[u.node_id].name if u.node_id in node_map else ""
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
            name = node_map[u.node_id].name if u.node_id in node_map else ""
            if "基础信息" in name:
                continue
            result.append({"name": name, "content": u.content.strip()[:1500]})
    return result

@router.get("/templates")
def list_templates(current_user=Depends(get_current_user)):
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

@router.get("/instances")
def list_instances(status: Optional[str] = None,
                   db: Session = Depends(get_db),
                   current_user=Depends(get_current_user)):
    q = db.query(WorkflowInstance).filter(WorkflowInstance.user_id == str(current_user.id))
    if status:
        q = q.filter(WorkflowInstance.status == status)
    try:
        insts = q.order_by(WorkflowInstance.created_at.desc()).all()
        return {"instances": [_instance_to_dict(db, i) for i in insts]}
    except Exception as e:
        logger.exception("工作流实例列表查询失败")
        raise HTTPException(status_code=500, detail=f"查询失败: {type(e).__name__}: {e}")

@router.post("/instances")
def create_instance(req: CreateInstanceRequest,
                    db: Session = Depends(get_db),
                    current_user=Depends(get_current_user)):
    tpl_row = _ensure_template_row(db, req.template_code)
    inst = WorkflowInstance(
        template_id=tpl_row.id,
        user_id=str(current_user.id),
        title=req.title,
        status="running",
        basic_info=req.workflow_context or {},
    )
    db.add(inst)
    db.flush()
    nodes = (
        db.query(WorkflowNode)
        .filter(WorkflowNode.template_id == tpl_row.id)
        .order_by(WorkflowNode.sort_order)
        .all()
    )
    for i, n in enumerate(nodes):
        db.add(NodeInstance(
            instance_id=inst.id, node_id=n.id,
            sort_order=i, status="pending", content="",
        ))
    db.commit()
    return {"id": inst.id}

@router.get("/instances/{inst_id}")
def get_instance(inst_id: str,
                 db: Session = Depends(get_db),
                 current_user=Depends(get_current_user)):
    inst = db.query(WorkflowInstance).filter(WorkflowInstance.id == inst_id).first()
    if not inst:
        raise HTTPException(status_code=404, detail="工作流不存在")
    return _instance_to_dict(db, inst)

@router.put("/instances/{inst_id}")
def update_instance(inst_id: str, req: UpdateInstanceRequest,
                    db: Session = Depends(get_db),
                    current_user=Depends(get_current_user)):
    inst = db.query(WorkflowInstance).filter(WorkflowInstance.id == inst_id).first()
    if not inst:
        raise HTTPException(status_code=404, detail="工作流不存在")
    if req.title is not None:
        inst.title = req.title
    if req.status is not None:
        inst.status = req.status
    if req.workflow_context is not None:
        inst.basic_info = req.workflow_context
        flag_modified(inst, "basic_info")
    elif req.basic_info is not None:
        inst.basic_info = _migrate_basic_info_to_context(req.basic_info)
        flag_modified(inst, "basic_info")
    db.commit()
    return {"ok": True}

@router.delete("/instances/{inst_id}")
def delete_instance(inst_id: str,
                    db: Session = Depends(get_db),
                    current_user=Depends(get_current_user)):
    inst = db.query(WorkflowInstance).filter(WorkflowInstance.id == inst_id).first()
    if not inst:
        raise HTTPException(status_code=404, detail="工作流不存在")
    db.query(NodeInstance).filter(NodeInstance.instance_id == inst_id).delete()
    db.delete(inst)
    db.commit()
    return {"ok": True}

@router.post("/instances/{inst_id}/parse-natural-language")
def parse_natural_language(inst_id: str, req: ParseNaturalLanguageRequest,
                           db: Session = Depends(get_db),
                           current_user=Depends(get_current_user)):
    inst = db.query(WorkflowInstance).filter(WorkflowInstance.id == inst_id).first()
    if not inst:
        raise HTTPException(status_code=404, detail="工作流不存在")
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
{req.text}

要求：
1. 只输出合法 JSON，不要任何解释、markdown 代码块标记或对话口吻；
2. 提取后必须将口语转化为体制内规范表述，禁止照搬口语词汇（如"看看""干得怎么样""聊一聊"）；
3. 未提取到的字段不要输出，或输出 null；不得虚构人名、日期、部门名称；
4. 描述中"总结上半年工作并部署下半年任务"这类内容，归入 purpose 或 topic，并用规范句式表达。

JSON："""
    try:
        raw = llm_service._call_vllm(
            [{"role": "user", "content": prompt}],
            temperature=0.1, max_tokens=800,
        )
        raw = re.sub(r'^```json\s*', '', raw.strip())
        raw = re.sub(r'\s*```$', '', raw.strip())
        parsed = json.loads(raw)
        parsed = {k: v for k, v in parsed.items() if v is not None and str(v).strip()}
    except Exception as e:
        logger.exception("自然语言解析失败")
        raise HTTPException(status_code=500, detail=f"解析失败: {e}")
    return {"parsed": parsed}

@router.post("/instances/{inst_id}/parse-key-value")
def parse_key_value(inst_id: str, req: ParseKeyValueRequest,
                    db: Session = Depends(get_db),
                    current_user=Depends(get_current_user)):
    inst = db.query(WorkflowInstance).filter(WorkflowInstance.id == inst_id).first()
    if not inst:
        raise HTTPException(status_code=404, detail="工作流不存在")
    current_ctx = _get_workflow_context(inst)
    parsed = {}
    for line in req.text.split('\n'):
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

@router.post("/instances/{inst_id}/confirm-context")
def confirm_context(inst_id: str, req: ConfirmContextRequest,
                    db: Session = Depends(get_db),
                    current_user=Depends(get_current_user)):
    inst = db.query(WorkflowInstance).filter(WorkflowInstance.id == inst_id).first()
    if not inst:
        raise HTTPException(status_code=404, detail="工作流不存在")
    current_ctx = _get_workflow_context(inst)
    new_ctx = dict(current_ctx)
    for key, val in req.workflow_context.items():
        if key in current_ctx and current_ctx[key] != val:
            if not req.confirm_overrides.get(key, False):
                continue
        new_ctx[key] = val
    inst.basic_info = new_ctx
    flag_modified(inst, "basic_info")
    db.commit()
    return {"ok": True, "workflow_context": new_ctx}

@router.put("/nodes/{node_inst_id}")
def update_node(node_inst_id: str, req: UpdateNodeRequest,
                db: Session = Depends(get_db),
                current_user=Depends(get_current_user)):
    ni = db.query(NodeInstance).filter(NodeInstance.id == node_inst_id).first()
    if not ni:
        raise HTTPException(status_code=404, detail="节点不存在")
    if req.content is not None:
        ni.content = req.content
        if ni.status == "pending":
            ni.status = "draft"
    if req.status is not None:
        ni.status = req.status
    db.commit()
    return {"ok": True, "status": ni.status}

@router.post("/nodes/{node_inst_id}/generate")
def generate_node(node_inst_id: str, req: GenerateNodeRequest,
                  db: Session = Depends(get_db),
                  current_user=Depends(get_current_user)):
    ni = db.query(NodeInstance).filter(NodeInstance.id == node_inst_id).first()
    if not ni:
        raise HTTPException(status_code=404, detail="节点不存在")
    node = db.query(WorkflowNode).filter(WorkflowNode.id == ni.node_id).first()
    inst = db.query(WorkflowInstance).filter(WorkflowInstance.id == ni.instance_id).first()
    if not node or not inst:
        raise HTTPException(status_code=404, detail="数据不完整")
    ctx = _get_workflow_context(inst)
    ctx_text = _build_context_text(ctx)
    upstream_items = _get_upstream_contents(db, inst, ni)
    upstream_text = ""
    if upstream_items:
        parts = []
        for item in upstream_items:
            parts.append(f"【{item['name']}】\n{item['content']}")
        upstream_text = "\n\n".join(parts)
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
{req.instruction or '无'}
{table_req}
写作纪律：
1. 直接输出正文，禁止"当然/好的/以下是"等对话口吻；
2. 禁止使用 markdown 符号（#、*、-、|），层级用"一、（一）、1."中文序号；
3. 禁止只列提纲，正文须为完整段落；
4. 不得虚构人名、数据，无依据处用"××"占位；
5. 公文类内容遵循 GB/T 9704-2012 格式表述习惯；
6. 基础信息中若残留口语化表述（如"总结会""聊一聊"），生成正文时必须转化为规范公文语言。"""
    try:
        content = llm_service._call_vllm(
            [{"role": "user", "content": prompt}],
            temperature=0.5, max_tokens=3000,
        )
    except Exception as e:
        logger.exception("节点生成失败")
        raise HTTPException(status_code=500, detail=f"生成失败: {e}")
    if req.save:
        ni.content = content
        if ni.status == "pending":
            ni.status = "draft"
        db.commit()
    return {"content": content, "status": ni.status, "saved": req.save}