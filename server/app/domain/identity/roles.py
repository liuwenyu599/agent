"""角色与权限模型。

审批流已从产品中移除；文档权限只保留独立的起草、编辑、文号、归档、导出与可见范围。
数据库中的历史角色字符串继续兼容，避免既有账号失效。
"""
from typing import Dict, List, Set

ROLE_SYSTEM_ADMIN = "system_admin"
ROLE_AUDITOR = "auditor"
ROLE_KNOWLEDGE_ADMIN = "knowledge_admin"
ROLE_OFFICE_MANAGER = "office_manager"
ROLE_LEADER = "leader"
ROLE_DEPT_HEAD = "dept_head"
ROLE_DRAFTER = "drafter"

LEGACY_ALIAS: Dict[str, str] = {
    "developer": ROLE_SYSTEM_ADMIN,
    "admin": ROLE_SYSTEM_ADMIN,
    "user": ROLE_DRAFTER,
}

ROLE_NAMES: Dict[str, str] = {
    ROLE_SYSTEM_ADMIN: "系统管理员",
    ROLE_AUDITOR: "审计员",
    ROLE_KNOWLEDGE_ADMIN: "知识库管理员",
    ROLE_OFFICE_MANAGER: "办公室管理员",
    ROLE_LEADER: "领导",
    ROLE_DEPT_HEAD: "科室负责人",
    ROLE_DRAFTER: "拟稿人",
}

ROLE_DESCRIPTIONS: Dict[str, str] = {
    ROLE_SYSTEM_ADMIN: "系统全部功能，含用户、角色、规则、文号、审计日志管理",
    ROLE_AUDITOR: "只读审计，可查看全部公文与审计记录",
    ROLE_KNOWLEDGE_ADMIN: "知识库建设与文档审核，可管理模板",
    ROLE_OFFICE_MANAGER: "办公室管理：文号、归档、格式规则与模板管理",
    ROLE_LEADER: "领导用户：可查看本科室文档并使用办公生产力能力",
    ROLE_DEPT_HEAD: "科室负责人：可查看本科室文档并管理本科室知识材料",
    ROLE_DRAFTER: "拟稿人：起草、修改、导出本人公文并使用知识库",
}

ACCEPTABLE_ROLES: Set[str] = set(LEGACY_ALIAS.keys()) | set(ROLE_NAMES.keys())

DOC_PERMS = [
    "doc:create", "doc:edit_own", "doc:number", "doc:archive", "doc:export",
    "doc:view_all", "doc:view_dept", "doc:view_self",
]
TPL_PERMS = ["tpl:view", "tpl:create", "tpl:edit", "tpl:delete", "tpl:publish", "tpl:init"]
FMT_PERMS = ["fmt:check", "fmt:fix", "fmt:rule_manage"]
PPT_PERMS = ["ppt:generate", "ppt:edit", "ppt:template_manage", "ppt:export"]
KB_PERMS = ["kb:view", "kb:upload", "kb:review", "kb:manage", "kb:delete"]
SYS_PERMS = ["sys:user_manage", "sys:role_manage", "sys:audit_view",
             "sys:config_manage", "sys:training_manage"]

ALL_PERMISSIONS: List[str] = DOC_PERMS + TPL_PERMS + FMT_PERMS + PPT_PERMS + KB_PERMS + SYS_PERMS

PERMISSION_NAMES: Dict[str, str] = {
    "doc:create": "起草公文", "doc:edit_own": "编辑本人公文",
    "doc:number": "编制文号", "doc:archive": "归档", "doc:export": "导出公文",
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

DEFAULT_ROLE_PERMS: Dict[str, Set[str]] = {
    ROLE_SYSTEM_ADMIN: set(ALL_PERMISSIONS),
    ROLE_AUDITOR: {
        "doc:view_all", "doc:export", "tpl:view", "fmt:check", "ppt:generate", "ppt:edit",
        "ppt:export", "kb:view", "sys:audit_view",
    },
    ROLE_KNOWLEDGE_ADMIN: {
        "doc:create", "doc:edit_own", "doc:export", "doc:view_dept",
        "tpl:view", "tpl:create", "tpl:edit", "tpl:publish", "tpl:init",
        "fmt:check", "fmt:fix", "fmt:rule_manage",
        "ppt:generate", "ppt:edit", "ppt:export",
        "kb:view", "kb:upload", "kb:review", "kb:manage", "kb:delete",
    },
    ROLE_OFFICE_MANAGER: {
        "doc:create", "doc:edit_own", "doc:number", "doc:archive", "doc:export", "doc:view_all",
        "tpl:view", "tpl:create", "tpl:edit", "tpl:publish",
        "fmt:check", "fmt:fix", "fmt:rule_manage",
        "ppt:generate", "ppt:edit", "ppt:export", "kb:view", "kb:upload",
    },
    ROLE_LEADER: {
        "doc:create", "doc:edit_own", "doc:export", "doc:view_dept",
        "tpl:view", "fmt:check", "fmt:fix",
        "ppt:generate", "ppt:edit", "ppt:export", "kb:view",
    },
    ROLE_DEPT_HEAD: {
        "doc:create", "doc:edit_own", "doc:export", "doc:view_dept",
        "tpl:view", "tpl:create", "tpl:edit",
        "fmt:check", "fmt:fix",
        "ppt:generate", "ppt:edit", "ppt:export", "kb:view", "kb:upload",
    },
    ROLE_DRAFTER: {
        "doc:create", "doc:edit_own", "doc:export", "doc:view_self",
        "tpl:view", "fmt:check", "fmt:fix",
        "ppt:generate", "ppt:edit", "ppt:export", "kb:view", "kb:upload",
    },
}

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
    if not role:
        return ROLE_DRAFTER
    return LEGACY_ALIAS.get(role, role)


def role_name_of(role: str) -> str:
    return ROLE_NAMES.get(normalize_role(role), role or "未分配")


def data_scope_of(role: str) -> str:
    return ROLE_DATA_SCOPE.get(normalize_role(role), "self")


def perms_of(role: str) -> Set[str]:
    return set(DEFAULT_ROLE_PERMS.get(normalize_role(role), DEFAULT_ROLE_PERMS[ROLE_DRAFTER]))


def has_perm(role: str, perm: str) -> bool:
    return perm in perms_of(role)