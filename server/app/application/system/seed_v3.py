"""v3.0 种子数据：角色权限矩阵 + 党政机关公文格式国标规则集

设计原则：
- 全部**幂等**，可重复执行（按唯一键 upsert，不重复插入）。
- 种子失败只告警不阻断启动（与内置公文模板的处理方式一致）。
- 规则全部标注依据条款，便于司法局核对与调整。
"""
import logging
from typing import Dict, List

from sqlalchemy.orm import Session

from app.domain.identity.roles import (
    ALL_PERMISSIONS, DEFAULT_ROLE_PERMS, PERMISSION_MODULES, PERMISSION_NAMES,
    ROLE_DESCRIPTIONS, ROLE_NAMES, ROLE_DATA_SCOPE)
from app.infrastructure.database.models.format_check import FormatRuleModel
from app.infrastructure.database.models.identity import UserModel
from app.infrastructure.database.models.system import SystemConfigModel

logger = logging.getLogger(__name__)

# ---------------- 角色 / 权限 ----------------
try:
    from app.infrastructure.database.models.rbac import (
        PermissionModel, RoleModel, RolePermissionModel)
    _RBAC_MODELS = True
except Exception:  # 表尚未建立时静默跳过，不影响启动
    _RBAC_MODELS = False
    RoleModel = PermissionModel = RolePermissionModel = None


def seed_rbac(db: Session) -> dict:
    """灌入 7 个角色 + 全部权限码 + 角色权限矩阵。"""
    if not _RBAC_MODELS:
        return {"roles": 0, "permissions": 0, "role_permissions": 0, "skipped": True}

    for code, name in ROLE_NAMES.items():
        row = db.get(RoleModel, code)
        if row is None:
            db.add(RoleModel(code=code, name=name,
                             description=ROLE_DESCRIPTIONS.get(code, ""),
                             is_system=True, sort_order=list(ROLE_NAMES).index(code)))
        else:
            row.name = name
            row.description = ROLE_DESCRIPTIONS.get(code, "")

    for i, code in enumerate(ALL_PERMISSIONS):
        row = db.get(PermissionModel, code)
        if row is None:
            db.add(PermissionModel(code=code, name=PERMISSION_NAMES.get(code, code),
                                   module=PERMISSION_MODULES.get(code, ""), sort_order=i))
        else:
            row.name = PERMISSION_NAMES.get(code, code)

    db.flush()
    count = 0
    for role_code, perms in DEFAULT_ROLE_PERMS.items():
        for p in perms:
            exist = db.get(RolePermissionModel, (role_code, p))
            if exist is None:
                db.add(RolePermissionModel(role_code=role_code, permission_code=p))
                count += 1
    db.commit()
    return {"roles": len(ROLE_NAMES), "permissions": len(ALL_PERMISSIONS),
            "role_permissions": count}


def sync_user_data_scope(db: Session) -> int:
    """按当前角色推导 users.data_scope。

    data_scope 是角色派生值（当前无人工编辑入口），因此每次启动都按角色校正，
    保证管理员改名/换角色后可见范围同步跟上；role_legacy 始终保留原始值不受影响。
    """
    n = 0
    try:
        from app.domain.identity.roles import data_scope_of
        for u in db.query(UserModel).all():
            want = data_scope_of(u.role)
            if u.data_scope != want:
                u.data_scope = want
                n += 1
        if n:
            db.commit()
    except Exception as e:
        logger.warning("同步用户数据范围失败（不影响业务）: %s", e)
    return n


# ---------------- 党政机关公文格式 GB/T 9704-2012 ----------------
# target 取值：page / title / body / heading1 / heading2 / signature / date / general
# severity：error=错误（必须改） / warning=警告（建议改） / info=提示
GBT_RULESET = "gb9704"

GBT_RULES: List[Dict] = [
    # 页面设置（GB/T 9704-2012 6.1 用纸与页边距）
    {"name": "页面上边距 37mm", "target": "page",
     "checks": {"top_margin_cm": 3.7}, "severity": "error",
     "remark": "GB/T 9704-2012 6.1：上白边（天头）37mm±1mm"},
    {"name": "页面下边距 35mm", "target": "page",
     "checks": {"bottom_margin_cm": 3.5}, "severity": "error",
     "remark": "GB/T 9704-2012 6.1：下白边（地脚）35mm±1mm"},
    {"name": "页面左边距 28mm", "target": "page",
     "checks": {"left_margin_cm": 2.8}, "severity": "error",
     "remark": "GB/T 9704-2012 6.1：左白边（订口）28mm±1mm"},
    {"name": "页面右边距 26mm", "target": "page",
     "checks": {"right_margin_cm": 2.6}, "severity": "error",
     "remark": "GB/T 9704-2012 6.1：右白边（翻口）26mm±1mm"},

    # 标题（7.3.1 二号小标宋体字，编排于红色分隔线下空二行，分一行或多行居中排布）
    {"name": "标题字号二号（22磅）", "target": "title",
     "checks": {"font_size_pt": 22}, "severity": "error",
     "remark": "GB/T 9704-2012 7.3.1：标题用 2 号小标宋体字"},
    {"name": "标题居中排布", "target": "title",
     "checks": {"alignment": "center"}, "severity": "error",
     "remark": "GB/T 9704-2012 7.3.1：标题分一行或多行居中排布"},
    {"name": "标题字体小标宋", "target": "title",
     "checks": {"font_name": "方正小标宋简体"}, "severity": "warning",
     "remark": "GB/T 9704-2012 7.3.1：小标宋体字；部分单位以黑体替代，故定为警告"},
    {"name": "标题不加粗", "target": "title",
     "checks": {"bold": False}, "severity": "warning",
     "remark": "小标宋为自带字形，不应再加粗"},
    {"name": "标题段后间距 0", "target": "title",
     "checks": {"space_after_pt": 0}, "severity": "info",
     "remark": "标题与正文之间不应有多余间距"},

    # 正文（7.3.3 三号仿宋_GB2312，每自然段左空二字，回行顶格）
    {"name": "正文字号三号（16磅）", "target": "body",
     "checks": {"font_size_pt": 16}, "severity": "error",
     "remark": "GB/T 9704-2012 7.3.3：正文用 3 号仿宋_GB2312 字"},
    {"name": "正文首行缩进 2 字符", "target": "body",
     "checks": {"first_line_indent_chars": 2}, "severity": "error",
     "remark": "GB/T 9704-2012 7.3.3：每自然段左空二字，回行顶格"},
    {"name": "正文行距固定值 28.8 磅", "target": "body",
     "checks": {"line_spacing_pt": 28.8}, "severity": "warning",
     "remark": "GB/T 9704-2012 7.3.3：一般每面排 22 行、每行 28 字（约固定值 28.8 磅）"},
    {"name": "正文段前段后间距 0", "target": "body",
     "checks": {"space_before_pt": 0, "space_after_pt": 0}, "severity": "info",
     "remark": "自然段之间不另设间距"},

    # 层次序号（7.3.3：一、用黑体；（一）用楷体_GB2312；1. 用仿宋加粗）
    {"name": "一级标题「一、」字号三号", "target": "heading1",
     "checks": {"font_size_pt": 16}, "severity": "warning",
     "remark": "GB/T 9704-2012 7.3.3：第一层「一、」用 3 号字"},
    {"name": "一级标题「一、」黑体", "target": "heading1",
     "checks": {"font_name": "黑体"}, "severity": "warning",
     "remark": "GB/T 9704-2012 7.3.3：第一层用黑体字"},
    {"name": "二级标题「（一）」字号三号", "target": "heading2",
     "checks": {"font_size_pt": 16}, "severity": "warning",
     "remark": "GB/T 9704-2012 7.3.3：第二层用 3 号字"},
    {"name": "二级标题「（一）」楷体", "target": "heading2",
     "checks": {"font_name": "楷体_GB2312"}, "severity": "warning",
     "remark": "GB/T 9704-2012 7.3.3：第二层用楷体_GB2312 字"},

    # 落款与成文日期（7.3.5 发文机关署名、7.3.6 成文日期右空四字）
    {"name": "发文机关署名右对齐", "target": "signature",
     "checks": {"alignment": "right"}, "severity": "warning",
     "remark": "GB/T 9704-2012 7.3.5：发文机关署名居右排布"},
    {"name": "成文日期右对齐", "target": "date",
     "checks": {"alignment": "right"}, "severity": "warning",
     "remark": "GB/T 9704-2012 7.3.6：成文日期右空四字编排"},

    # 全文通用
    {"name": "无连续多余空行", "target": "general",
     "checks": {"no_extra_blank_lines": True}, "severity": "warning",
     "remark": "段落间距应通过段前/段后设置实现，不应使用回车空行"},
    {"name": "无行尾空格", "target": "general",
     "checks": {"no_trailing_spaces": True}, "severity": "warning",
     "remark": "段末不应有多余空格，避免排版错位"},
]


def seed_format_rules(db: Session) -> int:
    """灌入国标格式规则；按 (ruleset, name) 去重，已存在则更新 checks 与依据。"""
    n = 0
    for r in GBT_RULES:
        exist = (db.query(FormatRuleModel)
                 .filter(FormatRuleModel.ruleset == GBT_RULESET,
                         FormatRuleModel.name == r["name"]).first())
        if exist is None:
            db.add(FormatRuleModel(
                name=r["name"], target=r["target"], checks=r["checks"],
                severity=r["severity"], is_active=True, is_default=True,
                ruleset=GBT_RULESET, remark=r["remark"]))
            n += 1
        else:
            changed = (exist.checks != r["checks"] or exist.severity != r["severity"]
                       or exist.remark != r["remark"])
            if changed:
                exist.checks = r["checks"]
                exist.severity = r["severity"]
                exist.remark = r["remark"]
                n += 1
    db.commit()
    return n


def seed_system_configs(db: Session) -> int:
    """默认系统配置（已存在则不覆盖，避免抹掉管理员的自定义设置）。"""
    defaults = [
        ("doc.number.daizi", "白云司", "公文文号代字"),
        ("doc.number.format", "{daizi}〔{year}〕{seq}号", "文号格式模板"),
        ("approval.default_flow", "dept,office,leader", "默认审核流转环节"),
        ("org.name", "白云区司法局", "机构名称"),
    ]
    n = 0
    for key, value, desc in defaults:
        exist = db.query(SystemConfigModel).filter(SystemConfigModel.key == key).first()
        if exist is None:
            db.add(SystemConfigModel(key=key, value=value, description=desc))
            n += 1
    if n:
        db.commit()
    return n


def run_all(db: Session) -> dict:
    result = {}
    for name, fn in (("rbac", seed_rbac), ("format_rules", seed_format_rules),
                     ("system_configs", seed_system_configs)):
        try:
            result[name] = fn(db)
        except Exception as e:
            # 禁止静默吞异常：种子失败必须留下完整堆栈，且返回值带 error 供调用方感知。
            logger.exception("种子 %s 执行失败（已回滚该段事务）: %s", name, e)
            db.rollback()
            result[name] = {"error": f"{type(e).__name__}: {e}"}
            result.setdefault("_errors", []).append(name)
    try:
        result["user_data_scope_synced"] = sync_user_data_scope(db)
    except Exception as e:
        logger.exception("同步用户数据范围失败: %s", e)
        result["user_data_scope_synced"] = {"error": f"{type(e).__name__}: {e}"}
        result.setdefault("_errors", []).append("user_data_scope_synced")
    return result
