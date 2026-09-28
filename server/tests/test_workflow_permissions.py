"""工作流程实例 / 节点访问边界回归测试。"""
import pytest

from app.application.workflow.service import WorkflowService
from app.core.exceptions import PermissionDeniedError
from app.domain.identity.entities import User
from app.domain.workflow.entities import NodeInstance, WorkflowInstance
from app.infrastructure.database.models.identity import UserModel


class _InstanceRepo:
    def __init__(self, instance):
        self.instance = instance

    def get(self, inst_id):
        return self.instance if self.instance and self.instance.id == inst_id else None


class _NodeRepo:
    def __init__(self, node):
        self.node = node

    def get(self, node_id):
        return self.node if self.node and self.node.id == node_id else None


class _Db:
    def __init__(self, owners):
        self.owners = owners

    def get(self, model, obj_id):
        assert model is UserModel
        return self.owners.get(obj_id)


def _user(uid, role="user", dept=""):
    return User(
        id=uid,
        username=uid,
        email=f"{uid}@test.local",
        hashed_password="x",
        role=role,
        department_code=dept,
    )


def _service(owner_dept="dept-a"):
    inst = WorkflowInstance(id="wf-1", template_id="tpl", user_id="owner",
                            title="测试流程", status="running", basic_info={})
    owner = UserModel(
        id="owner", username="owner", email="owner@test.local",
        hashed_password="x", role="user", department_code=owner_dept,
    )
    svc = WorkflowService.__new__(WorkflowService)
    svc.instances = _InstanceRepo(inst)
    svc.node_instances = _NodeRepo(
        NodeInstance(id="node-1", instance_id="wf-1", node_id="n", sort_order=0)
    )
    svc.db = _Db({"owner": owner})
    return svc


def test_owner_can_access_own_workflow():
    svc = _service()
    assert svc._get_instance_checked("wf-1", _user("owner", dept="dept-a")).id == "wf-1"


def test_other_user_cannot_access_workflow():
    svc = _service()
    with pytest.raises(PermissionDeniedError):
        svc._get_instance_checked("wf-1", _user("other", dept="dept-a"))


def test_system_admin_can_access_workflow():
    svc = _service()
    assert svc._get_instance_checked(
        "wf-1", _user("admin", role="developer", dept="dept-x")
    ).id == "wf-1"


def test_department_admin_only_accesses_same_department():
    svc = _service(owner_dept="dept-a")
    same = _user("ka-a", role="knowledge_admin", dept="dept-a")
    other = _user("ka-b", role="knowledge_admin", dept="dept-b")

    assert svc._get_instance_checked("wf-1", same).id == "wf-1"
    with pytest.raises(PermissionDeniedError):
        svc._get_instance_checked("wf-1", other)


def test_node_access_inherits_workflow_authorization():
    svc = _service(owner_dept="dept-a")

    assert svc._get_node_instance_checked(
        "node-1", _user("owner", dept="dept-a")
    ).id == "node-1"

    with pytest.raises(PermissionDeniedError):
        svc._get_node_instance_checked("node-1", _user("other", dept="dept-a"))
