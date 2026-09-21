"""角色与权限模型（v3.0）

设计取舍说明：
- 数据库 users.role 的**历史字符串保持不变**（developer / knowledge_admin / user / admin），
  避免为改名而做高风险数据迁移导致既有账号失效。
- 在此基础上新增 5 个贴合司法局实际分工的角色（office_manager / leader / dept_head /
  drafter / auditor），旧角色通过 LEGACY_ALIAS 映射到同等权限，两套并存、平滑过渡。
- 权限码命名规范 `<域>:<动作>`，域 ∈ doc/tpl/fmt/ppt/kb/sys。
- `doc:view_all / doc:view_dept / doc:view_self` 为**数据范围码**，不参与按钮级判定，
  只用于推导 VisibilityFilter。
- 权限表（roles/permissions/role_permissions）为空或查询失败时，
  一律回落本模块的 DEFAULT_ROLE_PERMS，**绝不允许出现全局 403**。
"""
from typing import Dict, List, Set

# ---------------- 角色 ----------------
ROLE_SYSTEM_ADMIN = "system_admin"
ROLE_AUDITOR = "auditor"
ROLE_KNOWLEDGE_ADMIN = "knowledge_admin"
ROLE_OFFICE_MANAGER = "office_manager"
ROLE_LEADER = "leader"
ROLE_DEPT_HEAD = "dept_head"
ROLE_DRAFTER = "drafter"

# 历史角色（库中仍可能存在）→ 新角色等价映射
LEGACY_ALIAS: Dict[str, str] = {
    "developer": ROLE_SYSTEM_ADMIN,
    "admin": ROLE_SYSTEM_ADMIN,
    "user": ROLE_DRAFTER,
}

ROLE_NAMES: Dict[str, str] = {
    ROLE_SYSTEM_ADMIN: "系统管理员",
    ROLE_AUDITOR: "审计员",
    ROLE_KNOWLEDGE_ADMIN: "知识库管理员",
    ROLE_OFFICE_MANAGER: "办公室核稿",
    ROLE_LEADER: "领导",
    ROLE_DEPT_HEAD: "科室负责人",
    ROLE_DRAFTER: "拟稿人",
}

ROLE_DESCRIPTIONS: Dict[str, str] = {
    ROLE_SYSTEM_ADMIN: "系统全部功能，含用户、角色、规则、文号、审计日志管理",
    ROLE_AUDITOR: "只读审计，可查看全部公文与流转记录，不参与办理",
    ROLE_KNOWLEDGE_ADMIN: "知识库建设与文档审核，可管理模板",
    ROLE_OFFICE_MANAGER: "办公室核稿：格式文种把关、编号、用印登记、分发归档",
    ROLE_LEADER: "分管领导/主要领导：审核与签发",
    ROLE_DEPT_HEAD: "科室负责人：本科室公文核稿",
    ROLE_DRAFTER: "拟稿人：起草、修改、提交送审本人公文",
}

# 历史角色 + 规范角色，均允许在 users.role 中落库（前端角色分配下拉使用）
ACCEPTABLE_ROLES: Set[str] = set(LEGACY_ALIAS.keys()) | set(ROLE_NAMES.keys())

# ---------------- 权限码 ----------------
DOC_PERMS = [
    "doc:create", "doc:edit_own", "doc:submit", "doc:review_dept", "doc:review_office",
    "doc:approve", "doc:number", "doc:seal", "doc:distribute", "doc:archive",
    "doc:terminate", "doc:export", "doc:view_all", "doc:view_dept", "doc:view_self",
]
TPL_PERMS = ["tpl:view", "tpl:create", "tpl:edit", "tpl:delete", "tpl:publish", "tpl:init"]
FMT_PERMS = ["fmt:check", "fmt:fix", "fmt:rule_manage"]
PPT_PERMS = ["ppt:generate", "ppt:edit", "ppt:template_manage", "ppt:export"]
KB_PERMS = ["kb:view", "kb:upload", "kb:review", "kb:manage", "kb:delete"]
SYS_PERMS = ["sys:user_manage", "sys:role_manage", "sys:audit_view",
             "sys:config_manage", "sys:training_manage"]

ALL_PERMISSIONS: List[str] = DOC_PERMS + TPL_PERMS + FMT_PERMS + PPT_PERMS + KB_PERMS + SYS_PERMS

PERMISSION_NAMES: Dict[str, str] = {
    "doc:create": "起草公文", "doc:edit_own": "编辑本人公文", "doc:submit": "提交送审",
    "doc:review_dept": "科室核稿", "doc:review_office": "办公室核稿", "doc:approve": "领导签发",
    "doc:number": "编制文号", "doc:seal": "用印登记", "doc:distribute": "分发登记",
    "doc:archive": "归档", "doc:terminate": "终止流程", "doc:export": "导出公文",
    "doc:view_all": "可见全部", "doc:view_dept": "可见本部门", "doc:view_self": "仅见本人",
    "tpl:view": "查看模板", "tpl:create": "新建模板", "tpl:edit": "编辑模板",
    "tpl:delete": "删除模板", "tpl:publish": "发布模板", "tpl:init": "初始化内置模板",
    "fmt:check": "格式校验", "fmt:fix": "生成修正稿", "fmt:rule_manage": "管理校验规则",
    "ppt:generate": "生成演示文稿", "ppt:edit": "编辑演示文稿",
    "ppt:template_manage": "管理PPT模板", "ppt:export": "导出演示文稿",
    "kb:view": "检索知识库", "kb:upload": "上传知识文档", "kb:review": "审核知识文档",
    "kb:manage": "管理知识库", "kb:delete": "删除知识文档",
    "sys:user_manage": "用户管理", "sys:role_manage": "角色权限管理",
    "sys:audit_view": "查看审计日志", "sys:config_manage": "系统配置",
    "sys:training_manage": "模型训练管理",
}

PERMISSION_MODULES: Dict[str, str] = {}
for _p in DOC_PERMS:
    PERMISSION_MODULES[_p] = "doc"
for _p in TPL_PERMS:
    PERMISSION_MODULES[_p] = "tpl"
for _p in FMT_PERMS:
    PERMISSION_MODULES[_p] = "fmt"
for _p in PPT_PERMS:
    PERMISSION_MODULES[_p] = "ppt"
for _p in KB_PERMS:
    PERMISSION_MODULES[_p] = "kb"
for _p in SYS_PERMS:
    PERMISSION_MODULES[_p] = "sys"

# ---------------- 角色 → 权限 ----------------
DEFAULT_ROLE_PERMS: Dict[str, Set[str]] = {
    ROLE_SYSTEM_ADMIN: set(ALL_PERMISSIONS),
    ROLE_AUDITOR: {
        "doc:view_all", "doc:export", "tpl:view", "fmt:check", "ppt:generate", "ppt:edit",
        "ppt:export", "kb:view", "sys:audit_view",
    },
    ROLE_KNOWLEDGE_ADMIN: {
        "doc:create", "doc:edit_own", "doc:submit", "doc:export", "doc:view_dept",
        "tpl:view", "tpl:create", "tpl:edit", "tpl:publish", "tpl:init",
        "fmt:check", "fmt:fix", "fmt:rule_manage",
        "ppt:generate", "ppt:edit", "ppt:export",
        "kb:view", "kb:upload", "kb:review", "kb:manage", "kb:delete",
    },
    ROLE_OFFICE_MANAGER: {
        "doc:create", "doc:edit_own", "doc:submit", "doc:review_dept", "doc:review_office",
        "doc:number", "doc:seal", "doc:distribute", "doc:archive", "doc:terminate",
        "doc:export", "doc:view_dept",
        "tpl:view", "tpl:create", "tpl:edit", "tpl:publish",
        "fmt:check", "fmt:fix", "fmt:rule_manage",
        "ppt:generate", "ppt:edit", "ppt:export", "kb:view", "kb:upload",
    },
    ROLE_LEADER: {
        "doc:create", "doc:edit_own", "doc:submit", "doc:review_dept", "doc:review_office",
        "doc:approve", "doc:terminate", "doc:export", "doc:view_dept",
        "tpl:view", "fmt:check", "fmt:fix",
        "ppt:generate", "ppt:edit", "ppt:export", "kb:view",
    },
    ROLE_DEPT_HEAD: {
        "doc:create", "doc:edit_own", "doc:submit", "doc:review_dept", "doc:terminate",
        "doc:export", "doc:view_dept",
        "tpl:view", "tpl:create", "tpl:edit",
        "fmt:check", "fmt:fix",
        "ppt:generate", "ppt:edit", "ppt:export", "kb:view", "kb:upload",
    },
    ROLE_DRAFTER: {
        "doc:create", "doc:edit_own", "doc:submit", "doc:export", "doc:view_self",
        "tpl:view", "fmt:check", "fmt:fix",
        "ppt:generate", "ppt:edit", "ppt:export", "kb:view", "kb:upload",
    },
}

# 角色默认数据可见范围
ROLE_DATA_SCOPE: Dict[str, str] = {
    ROLE_SYSTEM_ADMIN: "all",
    ROLE_AUDITOR: "all",
    ROLE_OFFICE_MANAGER: "all",
    ROLE_LEADER: "dept",
    ROLE_DEPT_HEAD: "dept",
    ROLE_KNOWLEDGE_ADMIN: "dept",
    ROLE_DRAFTER: "self",
}

VIEW_SCOPE_PERM = {"all": "doc:view_all", "dept": "doc:view_dept", "self": "doc:view_self"}


def normalize_role(role: str) -> str:
    """把历史角色字符串归一到新角色码。"""
    if not role:
        return ROLE_DRAFTER
    return LEGACY_ALIAS.get(role, role)


def role_name_of(role: str) -> str:
    return ROLE_NAMES.get(normalize_role(role), role or "未分配")


def data_scope_of(role: str) -> str:
    return ROLE_DATA_SCOPE.get(normalize_role(role), "self")


def perms_of(role: str) -> Set[str]:
    """角色权限集合。表数据不可用时回落代码常量。"""
    return set(DEFAULT_ROLE_PERMS.get(normalize_role(role), DEFAULT_ROLE_PERMS[ROLE_DRAFTER]))


def has_perm(role: str, perm: str) -> bool:
    return perm in perms_of(role)
