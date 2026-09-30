"""用户管理路由（管理端）。响应结构与旧系统一致。"""
import csv
import io
import re

from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.orm import Session

from app.application.audit.service import AuditService
from app.application.identity.dto import (
    ResetPasswordRequest,
    UserCreateRequest,
    UserUpdateRequest,
)
from app.application.identity.service import UserService
from app.core.exceptions import AppError
from app.domain.identity.entities import User
from app.infrastructure.database import get_db
from app.infrastructure.repositories.identity import SqlAlchemyUserRepository
from app.interfaces.deps import require_developer

router = APIRouter(prefix="/users", tags=["用户"])


def get_user_service(db: Session = Depends(get_db)) -> UserService:
    return UserService(SqlAlchemyUserRepository(db), db=db, audit=AuditService.from_db(db))


@router.get("/")
def list_users(
    admin: User = Depends(require_developer),
    svc: UserService = Depends(get_user_service),
):
    return [
        {
            "id": u.id,
            "username": u.username,
            "real_name": u.real_name,
            "email": u.email,
            "department": u.department,
            "department_code": getattr(u, "department_code", "") or "",
            "role": u.role,
            "is_active": u.is_active,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in svc.list_users()
    ]


@router.post("/")
def create_user(
    req: UserCreateRequest,
    admin: User = Depends(require_developer),
    svc: UserService = Depends(get_user_service),
):
    user = svc.create_user(admin, req.username, req.email, req.password,
                           req.real_name, req.department, req.role, req.department_code)
    return {"id": user.id, "message": "User created"}


@router.put("/{user_id}")
def update_user(
    user_id: str,
    req: UserUpdateRequest,
    admin: User = Depends(require_developer),
    svc: UserService = Depends(get_user_service),
):
    svc.update_user(admin, user_id, req.real_name, req.department,
                    req.is_active, req.role, req.department_code)
    return {"message": "User updated"}


@router.post("/{user_id}/reset-password")
def reset_password(
    user_id: str,
    req: ResetPasswordRequest,
    admin: User = Depends(require_developer),
    svc: UserService = Depends(get_user_service),
):
    """管理员重置他人密码：重置后该用户下次登录必须修改密码。"""
    svc.reset_password(admin, user_id, req.password)
    return {"message": "Password reset successfully", "must_change_password": True}


@router.delete("/{user_id}")
def delete_user(
    user_id: str,
    admin: User = Depends(require_developer),
    svc: UserService = Depends(get_user_service),
):
    svc.deactivate_user(admin, user_id)
    return {"message": "User deactivated"}


# ---------------- 批量导入（Excel / CSV） ----------------

_HEADER_ALIASES = {
    "username": ("username", "用户名", "账号"),
    "email": ("email", "邮箱", "电子邮件"),
    "real_name": ("real_name", "姓名", "真实姓名"),
    "department": ("department", "部门", "科室"),
    "department_code": ("department_code", "科室代码", "科室编码"),
    "role": ("role", "角色"),
    "password": ("password", "密码", "初始密码"),
}

_ROLE_ALIASES = {
    "user": "user", "普通用户": "user",
    "knowledge_admin": "knowledge_admin", "科室管理员": "knowledge_admin", "知识管理员": "knowledge_admin",
    "developer": "developer", "系统管理员": "developer",
}

DEFAULT_BATCH_PASSWORD = "123456"
_USERNAME_RE = re.compile(r"^[A-Za-z0-9]{3,32}$")


def _norm_header(text: str) -> str:
    text = (text or "").strip().lower()
    for key, aliases in _HEADER_ALIASES.items():
        if text in [a.lower() for a in aliases]:
            return key
    return ""


def _read_rows(filename: str, raw: bytes) -> list[dict]:
    """把上传的 csv/xlsx 解析为 [{username, email, ...}, ...]。"""
    name = (filename or "").lower()
    if name.endswith(".xlsx") or name.endswith(".xlsm"):
        try:
            from openpyxl import load_workbook
            wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
            ws = wb.active
            rows = [["" if c is None else str(c).strip() for c in row] for row in ws.iter_rows(values_only=True)]
        except Exception:
            raise AppError(400, "Excel 文件解析失败，请确认为有效的 .xlsx 文件")
    else:
        text = None
        for enc in ("utf-8-sig", "utf-8", "gbk"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise AppError(400, "CSV 编码无法识别，请使用 UTF-8 或 GBK 编码")
        rows = [[c.strip() for c in r] for r in csv.reader(io.StringIO(text)) if any(c.strip() for c in r)]

    if not rows:
        raise AppError(400, "文件内容为空")

    headers = [_norm_header(h) for h in rows[0]]
    if "username" not in headers:
        raise AppError(400, "未找到「用户名」列，表头支持：用户名/邮箱/姓名/科室代码/角色/初始密码")

    out = []
    for line_no, row in enumerate(rows[1:], start=2):
        record = {}
        for idx, key in enumerate(headers):
            if key and idx < len(row):
                record[key] = row[idx]
        if not any(record.values()):
            continue
        record["_row"] = line_no
        out.append(record)
    return out


@router.post("/batch-import")
def batch_import_users(
    file: UploadFile = File(...),
    admin: User = Depends(require_developer),
    svc: UserService = Depends(get_user_service),
):
    """批量创建用户：上传 .xlsx 或 .csv。

    用户名规则与单个创建保持一致：仅 3~32 位英文字母或数字。
    初始密码缺省为 123456；所有批量创建的用户 must_change_password=True，首次登录强制改密。
    逐行处理：单行失败不影响其他行，返回每行结果。
    """
    raw = file.file.read()
    if not raw:
        raise AppError(400, "文件内容为空")
    if len(raw) > 5 * 1024 * 1024:
        raise AppError(400, "文件过大（不超过 5MB）")

    rows = _read_rows(file.filename or "", raw)
    if not rows:
        raise AppError(400, "未解析到有效数据行")
    if len(rows) > 500:
        raise AppError(400, "单次最多导入 500 行")

    results = []
    succeeded = 0
    for rec in rows:
        username = rec.get("username", "").strip()
        email = rec.get("email", "").strip()
        real_name = rec.get("real_name", "").strip()
        department = rec.get("department", "").strip()
        department_code = rec.get("department_code", "").strip()
        role_raw = rec.get("role", "").strip() or "user"
        role = _ROLE_ALIASES.get(role_raw.lower(), _ROLE_ALIASES.get(role_raw, ""))
        password = rec.get("password", "").strip() or DEFAULT_BATCH_PASSWORD
        row_no = rec["_row"]

        if not username or not email:
            results.append({"row": row_no, "username": username, "ok": False,
                            "message": "用户名和邮箱不能为空"})
            continue
        if not _USERNAME_RE.fullmatch(username):
            results.append({"row": row_no, "username": username, "ok": False,
                            "message": "用户名只能使用 3~32 位英文字母或数字，不能包含中文、空格或符号"})
            continue
        if not role:
            results.append({"row": row_no, "username": username, "ok": False,
                            "message": f"角色无效：{role_raw}（支持 普通用户/科室管理员）"})
            continue
        try:
            svc.create_user(admin, username, email, password,
                            real_name, department, role, department_code)
            succeeded += 1
            results.append({"row": row_no, "username": username, "ok": True, "message": "创建成功"})
        except Exception as e:
            msg = getattr(e, "message", None) or str(e)
            results.append({"row": row_no, "username": username, "ok": False, "message": msg})

    return {
        "total": len(rows),
        "succeeded": succeeded,
        "failed": len(rows) - succeeded,
        "results": results,
    }
