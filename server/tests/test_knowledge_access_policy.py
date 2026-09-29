"""知识库权限矩阵交付回归测试。"""
from types import SimpleNamespace

from app.application.knowledge.access import KnowledgeAccessPolicy


class _Db:
    def get(self, *_args, **_kwargs):
        return None


def _user(uid, role, dept=""):
    return SimpleNamespace(
        id=uid, role=role, department_code=dept, department="")


def _kb(kb_type="public", dept="", owner=""):
    return SimpleNamespace(
        id="kb", kb_type=kb_type, department_code=dept,
        owner_id=owner, is_active=True)


def test_department_admin_can_read_global_public_knowledge():
    policy = KnowledgeAccessPolicy(_Db())
    user = _user("ka", "knowledge_admin", "justice")
    assert policy.can_read_kb(_kb("public", ""), user) is True


def test_system_admin_can_manage_global_public_knowledge():
    policy = KnowledgeAccessPolicy(_Db())
    user = _user("dev", "developer", "")
    assert policy.can_manage_kb(_kb("public", ""), user) is True
    assert policy.can_write_kb(_kb("public", ""), user) is True


def test_department_admin_only_manages_own_department_knowledge():
    policy = KnowledgeAccessPolicy(_Db())
    user = _user("ka", "knowledge_admin", "justice")
    assert policy.can_manage_kb(_kb("public", "justice"), user) is True
    assert policy.can_write_kb(_kb("public", "justice"), user) is True
    assert policy.can_manage_kb(_kb("public", "finance"), user) is False
    assert policy.can_write_kb(_kb("public", "finance"), user) is False
