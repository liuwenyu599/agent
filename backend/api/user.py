from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from backend.database.postgres import get_db
from backend.database.models import User
from backend.auth.permission import require_admin_or_above
from backend.auth.jwt import get_password_hash

router = APIRouter(prefix="/users", tags=["用户"])

class UserCreateRequest(BaseModel):
    username: str
    email: str
    password: str
    real_name: str = ""
    department: str = ""
    role: str = "user"

class UserUpdateRequest(BaseModel):
    real_name: str = None
    department: str = None
    is_active: bool = None
    role: str = None

class ResetPasswordRequest(BaseModel):
    password: str

@router.get("/")
async def list_users(admin: User = Depends(require_admin_or_above), db: Session = Depends(get_db)):
    users = db.query(User).all()
    return [{
        "id": u.id,
        "username": u.username,
        "real_name": u.real_name,
        "email": u.email,
        "department": u.department,
        "role": u.role,
        "is_active": u.is_active,
        "created_at": u.created_at.isoformat() if u.created_at else None
    } for u in users]

@router.post("/")
async def create_user(
    req: UserCreateRequest,
    admin: User = Depends(require_admin_or_above),
    db: Session = Depends(get_db)
):
    # 权限控制：只有 developer 可以创建 developer
    if req.role == "developer" and admin.role != "developer":
        raise HTTPException(status_code=403, detail="只有系统管理员可以创建系统管理员")

    # 知识管理员只能创建 user 和 knowledge_admin
    if admin.role == "knowledge_admin" and req.role not in ["user", "knowledge_admin"]:
        raise HTTPException(status_code=403, detail="知识管理员只能创建普通用户和知识管理员")

    if db.query(User).filter(User.username == req.username).first():
        raise HTTPException(status_code=400, detail="Username exists")

    if db.query(User).filter(User.email == req.email).first():
        raise HTTPException(status_code=400, detail="Email exists")

    user = User(
        username=req.username,
        email=req.email,
        hashed_password=get_password_hash(req.password),
        real_name=req.real_name,
        department=req.department,
        role=req.role
    )
    db.add(user)
    db.commit()

    return {"id": user.id, "message": "User created"}

@router.put("/{user_id}")
async def update_user(
    user_id: str,
    req: UserUpdateRequest,
    admin: User = Depends(require_admin_or_above),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # 权限控制：只有 developer 可以修改角色为 developer
    if req.role is not None:
        if req.role == "developer" and admin.role != "developer":
            raise HTTPException(status_code=403, detail="只有系统管理员可以设置系统管理员角色")
        # 不能修改自己的角色
        if user.id == admin.id and req.role != admin.role:
            raise HTTPException(status_code=403, detail="不能修改自己的角色")

    if req.real_name is not None:
        user.real_name = req.real_name
    if req.department is not None:
        user.department = req.department
    if req.is_active is not None:
        user.is_active = req.is_active
    if req.role is not None:
        user.role = req.role

    db.commit()
    return {"message": "User updated"}

@router.post("/{user_id}/reset-password")
async def reset_password(
    user_id: str,
    req: ResetPasswordRequest,
    admin: User = Depends(require_admin_or_above),
    db: Session = Depends(get_db)
):
    """管理员重置用户密码"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="密码至少6位")

    user.hashed_password = get_password_hash(req.password)
    db.commit()

    return {"message": "Password reset successfully"}

@router.delete("/{user_id}")
async def delete_user(
    user_id: str,
    admin: User = Depends(require_admin_or_above),
    db: Session = Depends(get_db)
):
    """删除用户（软删除）"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.id == admin.id:
        raise HTTPException(status_code=403, detail="不能删除自己")

    user.is_active = False
    db.commit()

    return {"message": "User deactivated"}