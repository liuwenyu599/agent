from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from backend.database.postgres import get_db
from backend.database.models import User
from backend.auth.jwt import decode_token

security = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    payload = decode_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")
    
    return user

def require_knowledge_admin(user: User = Depends(get_current_user)):
    """知识管理员权限"""
    if user.role not in ["knowledge_admin", "developer", "admin"]:
        raise HTTPException(status_code=403, detail="Knowledge admin required")
    return user

def require_developer(user: User = Depends(get_current_user)):
    """开发者权限（系统管理员）"""
    if user.role != "developer":
        raise HTTPException(status_code=403, detail="Developer required")
    return user

def require_admin_or_above(user: User = Depends(get_current_user)):
    """管理员及以上权限（knowledge_admin 或 developer）"""
    if user.role not in ["knowledge_admin", "developer", "admin"]:
        raise HTTPException(status_code=403, detail="Admin required")
    return user
