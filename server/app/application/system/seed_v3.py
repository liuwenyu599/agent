"""v3.0 种子数据：角色权限矩阵 + 党政机关公文格式国标规则集

设计原则：
- 全部**幂等**，可重复执行（按唯一键 upsert，不重复插入）。
- 种子失败只告警不阻断启动（与内置公文模板的处理方式一致）。
- 规则全部标注依据条款，便于司法局核对与调整。
"""
import logging
from typing import Dict, List

from sqlalchemy.orm import Session

from app.domain.official_document_format import GBT_RULESET, GBT_RULES
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
