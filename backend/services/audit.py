from backend.database.postgres import SessionLocal
from backend.database.models import AuditLog
class AuditService:
    def __init__(self, db=None): self.db = db or SessionLocal()
    def log(self, user_id, action, resource_type=None, resource_id=None, detail=None, ip_address=None):
        log = AuditLog(user_id=user_id, action=action, resource_type=resource_type, resource_id=resource_id, detail=detail, ip_address=ip_address)
        self.db.add(log); self.db.commit()
    def log_login(self, user_id, ip=None, success=True): self.log(user_id, "login" if success else "login_failed", detail=f"登录{'成功' if success else '失败'}", ip_address=ip)
    def log_upload(self, user_id, doc_id, title, ip=None): self.log(user_id, "document_upload", "document", doc_id, f"上传文档: {title}", ip)
    def log_review(self, user_id, doc_id, action, ip=None): self.log(user_id, f"document_{action}", "document", doc_id, f"文档审核: {action}", ip)
    def get_logs(self, user_id=None, action=None, limit=100):
        q = self.db.query(AuditLog)
        if user_id: q = q.filter(AuditLog.user_id == user_id)
        if action: q = q.filter(AuditLog.action == action)
        return q.order_by(AuditLog.created_at.desc()).limit(limit).all()
