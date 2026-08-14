from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from backend.database.postgres import get_db
from backend.database.models import User
from backend.auth.jwt import verify_password, get_password_hash, create_access_token
from backend.auth.permission import get_current_user

router = APIRouter(prefix="/auth", tags=["认证"])

class LoginRequest(BaseModel):
    username: str
    password: str

class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str
    real_name: str = ""
    department: str = ""
    role: str = "user"

@router.post("/login")
async def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == req.username).first()
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    
    token = create_access_token({"sub": user.id, "username": user.username, "role": user.role})
    
    return {
        "access_token": token,
        "user": {
            "id": user.id,
            "username": user.username,
            "real_name": user.real_name,
            "role": user.role
        }
    }

@router.post("/register")
async def register(
    req: RegisterRequest, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """已登录用户注册新用户（需要权限）"""
    # 检查用户名
    if db.query(User).filter(User.username == req.username).first():
        raise HTTPException(status_code=400, detail="用户名已存在")
    
    # 检查邮箱
    if db.query(User).filter(User.email == req.email).first():
        raise HTTPException(status_code=400, detail="邮箱已存在")
    
    # 权限控制
    allowed_roles = []
    if current_user.role == "developer":
        allowed_roles = ["user", "knowledge_admin", "developer"]
    elif current_user.role == "knowledge_admin":
        allowed_roles = ["user", "knowledge_admin"]
    else:
        raise HTTPException(status_code=403, detail="普通用户无权注册新用户")
    
    if req.role not in allowed_roles:
        raise HTTPException(status_code=403, detail=f"无权注册该角色，允许: {', '.join(allowed_roles)}")
    
    # 创建用户
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
    
    return {
        "message": "用户创建成功",
        "user": {
            "id": user.id,
            "username": user.username,
            "real_name": user.real_name,
            "role": user.role
        }
    }

@router.post("/register-first")
async def register_first(req: RegisterRequest, db: Session = Depends(get_db)):
    """首次注册，创建系统管理员（developer）"""
    # 检查是否已有用户
    existing_user = db.query(User).first()
    if existing_user:
        raise HTTPException(status_code=403, detail="系统已有用户，请登录后注册")
    
    # 首次注册必须是 developer
    if req.role != "developer":
        raise HTTPException(status_code=400, detail="首次注册必须是系统管理员(developer)角色")
    
    # 检查用户名
    if db.query(User).filter(User.username == req.username).first():
        raise HTTPException(status_code=400, detail="用户名已存在")
    
    # 检查邮箱
    if db.query(User).filter(User.email == req.email).first():
        raise HTTPException(status_code=400, detail="邮箱已存在")
    
    user = User(
        username=req.username,
        email=req.email,
        hashed_password=get_password_hash(req.password),
        real_name=req.real_name,
        department=req.department,
        role="developer"
    )
    db.add(user)
    db.commit()
    
    token = create_access_token({"sub": user.id, "username": user.username, "role": user.role})
    
    return {
        "access_token": token,
        "user": {
            "id": user.id,
            "username": user.username,
            "real_name": user.real_name,
            "role": user.role
        }
    }

@router.get("/check-first-user")
async def check_first_user(db: Session = Depends(get_db)):
    """检查是否是系统第一个用户"""
    count = db.query(User).count()
    return {"is_first": count == 0}

@router.get("/me")
async def get_me(user: User = Depends(get_current_user)):
    return {
        "id": user.id,
        "username": user.username,
        "real_name": user.real_name,
        "role": user.role,
        "department": user.department
    }
