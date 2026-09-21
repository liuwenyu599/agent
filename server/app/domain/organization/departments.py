"""科室（部门）字典：正式名称 + 简称。

- 正式名称用于公文、管理页面与导出件；
- 简称用于日常 UI 展示；
- code 是后端强隔离的主键（users / knowledge_bases / documents / templates / agent_configs
  均以 department_code 作为隔离维度）。
"""
from typing import Dict, List, NamedTuple


class Department(NamedTuple):
    code: str
    name: str          # 正式名称
    short_name: str    # 简称


DEPARTMENTS: List[Department] = [
    Department("bangongshi", "办公室", "办公室"),
    Department("fazhi", "法制与律师管理科", "法制科"),
    Department("zhifa", "行政复议应诉综合科", "执法科"),
    Department("fuyi", "行政复议科", "复议科"),
    Department("gongfa", "公共法律服务管理科", "公法科"),
    Department("shejiao", "社区矫正和安置帮教科", "社矫安帮科"),
    Department("renshi", "人事科", "人事科"),
    Department("jiguan", "机关党委", "机关党委"),
    Department("fayuan", "白云区法律援助处", "区法援处"),
    Department("gongzhi", "白云区公职律师事务所", "区公职所"),
]

DEPARTMENT_BY_CODE: Dict[str, Department] = {d.code: d for d in DEPARTMENTS}
DEPARTMENT_BY_NAME: Dict[str, Department] = {d.name: d for d in DEPARTMENTS}

# 检索作用域
SCOPE_GLOBAL = "GLOBAL"
# 个人知识库作用域前缀（仅 owner 可见）
SCOPE_USER_PREFIX = "USER:"


def dept_scope(code: str) -> str:
    """科室作用域标记，如 DEPT:fuyi。"""
    return f"DEPT:{code}"


def user_scope(user_id: str) -> str:
    """个人知识库作用域标记，如 USER:<user_id>，仅本人可召回。"""
    return f"{SCOPE_USER_PREFIX}{user_id}"


def resolve_code(name: str) -> str:
    """按 code / 正式名称 / 简称反查 code；未命中返回空串（不猜测归口）。"""
    if not name:
        return ""
    name = name.strip()
    if name in DEPARTMENT_BY_CODE:
        return name
    for d in DEPARTMENTS:
        if name == d.name or name == d.short_name:
            return d.code
    return ""
