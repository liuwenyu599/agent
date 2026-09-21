"""公文审核流转状态机（v3.0）

设计要点：
- 9 个持久状态 + RETURNED（瞬时记录态，不落 current_status，只写 action）。
- 15 条合法迁移集中在本文件的 TRANSITIONS 字典常量里，**不使用 if-else 链**。
- 每一步必须声明：触发动作、目标状态、所需权限码、守卫（如退回必填意见 ≥5 字）。
- 终态（ARCHIVED / TERMINATED）无出边。
- 审核流**完全不依赖 AI**：AI 不可用也必须能走完整条链路。

司法局实际链条（固定 3 段，可跳过、可退回、可撤回）：
  拟稿 DRAFT
    → 科室核稿 PENDING_DEPT
    → 办公室核稿 PENDING_OFFICE
    → 领导签发 PENDING_LEADER
    → 已签发 APPROVED
    → 已编号 NUMBERED（文号可配置，默认「白云司〔2026〕18号」）
    → 已印发 ISSUED（用印/分发只登记，不产生审批节点）
    → 已归档 ARCHIVED
"""
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

# ---------------- 状态 ----------------
DRAFT = "DRAFT"
PENDING_DEPT = "PENDING_DEPT"
PENDING_OFFICE = "PENDING_OFFICE"
PENDING_LEADER = "PENDING_LEADER"
APPROVED = "APPROVED"
NUMBERED = "NUMBERED"
ISSUED = "ISSUED"
ARCHIVED = "ARCHIVED"
TERMINATED = "TERMINATED"

STATUS_NAMES: Dict[str, str] = {
    DRAFT: "草稿",
    PENDING_DEPT: "科室核稿中",
    PENDING_OFFICE: "办公室核稿中",
    PENDING_LEADER: "领导签发中",
    APPROVED: "已签发",
    NUMBERED: "已编号",
    ISSUED: "已印发",
    ARCHIVED: "已归档",
    TERMINATED: "已终止",
}

# 状态 → 流转环节码
STATUS_STEP: Dict[str, str] = {
    DRAFT: "draft",
    PENDING_DEPT: "dept",
    PENDING_OFFICE: "office",
    PENDING_LEADER: "leader",
    APPROVED: "number",
    NUMBERED: "issue",
    ISSUED: "archive",
    ARCHIVED: "done",
    TERMINATED: "done",
}

STEP_NAMES: Dict[str, str] = {
    "draft": "拟稿", "dept": "科室核稿", "office": "办公室核稿",
    "leader": "领导签发", "number": "编制文号", "issue": "用印印发",
    "archive": "归档", "done": "已结束",
}

TERMINAL_STATES = (ARCHIVED, TERMINATED)

# ---------------- 动作 ----------------
ACT_SUBMIT = "submit"
ACT_APPROVE = "approve"
ACT_RETURN_PREV = "return_prev"
ACT_RETURN_DRAFTER = "return_drafter"
ACT_TERMINATE = "terminate"
ACT_WITHDRAW = "withdraw"
ACT_NUMBER = "number"
ACT_SEAL = "seal"
ACT_DISTRIBUTE = "distribute"
ACT_ARCHIVE = "archive"

ACTION_NAMES: Dict[str, str] = {
    ACT_SUBMIT: "提交送审", ACT_APPROVE: "同意", ACT_RETURN_PREV: "退回上一节点",
    ACT_RETURN_DRAFTER: "退回拟稿人", ACT_TERMINATE: "终止", ACT_WITHDRAW: "撤回",
    ACT_NUMBER: "编制文号", ACT_SEAL: "用印登记", ACT_DISTRIBUTE: "分发登记",
    ACT_ARCHIVE: "归档",
}

# 退回/终止类动作：必须填写意见
COMMENT_REQUIRED_ACTIONS = (ACT_RETURN_PREV, ACT_RETURN_DRAFTER, ACT_TERMINATE)
MIN_COMMENT_LEN = 5


@dataclass(frozen=True)
class Transition:
    to_status: str
    perm: str                 # 触发所需权限码
    need_comment: bool = False
    is_return: bool = False   # 退回类：状态不前进，只记录 action
    allow_submitter: bool = False  # 拟稿人本人可触发（撤回）


# ---------------- 15 条合法迁移 ----------------
# key = (当前状态, 动作)
TRANSITIONS: Dict[Tuple[str, str], Transition] = {
    # 1-2 拟稿 → 送审
    (DRAFT, ACT_SUBMIT):        Transition(PENDING_DEPT, "doc:submit"),
    (DRAFT, ACT_SUBMIT + "_skip_dept"): Transition(PENDING_OFFICE, "doc:submit"),

    # 3-5 科室核稿
    (PENDING_DEPT, ACT_APPROVE):        Transition(PENDING_OFFICE, "doc:review_dept"),
    (PENDING_DEPT, ACT_RETURN_PREV):    Transition(DRAFT, "doc:review_dept",
                                                   need_comment=True, is_return=True),
    (PENDING_DEPT, ACT_TERMINATE):      Transition(TERMINATED, "doc:terminate",
                                                   need_comment=True),

    # 6-8 办公室核稿
    (PENDING_OFFICE, ACT_APPROVE):      Transition(PENDING_LEADER, "doc:review_office"),
    (PENDING_OFFICE, ACT_RETURN_PREV):  Transition(PENDING_DEPT, "doc:review_office",
                                                   need_comment=True, is_return=True),
    (PENDING_OFFICE, ACT_TERMINATE):    Transition(TERMINATED, "doc:terminate",
                                                   need_comment=True),

    # 9-11 领导签发
    (PENDING_LEADER, ACT_APPROVE):      Transition(APPROVED, "doc:approve"),
    (PENDING_LEADER, ACT_RETURN_DRAFTER): Transition(DRAFT, "doc:approve",
                                                     need_comment=True, is_return=True),
    (PENDING_LEADER, ACT_TERMINATE):    Transition(TERMINATED, "doc:terminate",
                                                   need_comment=True),

    # 12-14 签发后：编号 → 用印印发 → 归档（只登记，不产生审批等待）
    (APPROVED, ACT_NUMBER):      Transition(NUMBERED, "doc:number"),
    (NUMBERED, ACT_SEAL):        Transition(ISSUED, "doc:seal"),
    (NUMBERED, ACT_DISTRIBUTE):  Transition(ISSUED, "doc:distribute"),
    (ISSUED, ACT_ARCHIVE):       Transition(ARCHIVED, "doc:archive"),

    # 15 拟稿人撤回（仅流转中、尚未签发）
    (PENDING_DEPT, ACT_WITHDRAW):   Transition(DRAFT, "doc:submit",
                                               allow_submitter=True, is_return=True),
    (PENDING_OFFICE, ACT_WITHDRAW): Transition(DRAFT, "doc:submit",
                                               allow_submitter=True, is_return=True),
}


def next_step_of(status: str, flow: Optional[list]) -> str:
    """根据状态与流程配置给出下一环节名。"""
    return STATUS_STEP.get(status, "")


def available_actions(status: str, flow: Optional[list]) -> list:
    """当前状态下所有可触发的动作（用于前端渲染按钮）。"""
    return sorted({act for (st, act) in TRANSITIONS if st == status})


def resolve(from_status: str, action: str, flow: Optional[list]) -> Optional[Transition]:
    """解析迁移；支持「跳过本科室核稿」的流程配置。"""
    tr = TRANSITIONS.get((from_status, action))
    if tr is not None:
        # 流程未配置 dept 环节时，同意动作直接进办公室
        if action == ACT_APPROVE and from_status == PENDING_DEPT:
            return tr
        return tr
    # DRAFT 提交时按 flow 决定起点
    if from_status == DRAFT and action == ACT_SUBMIT and flow:
        steps = [s for s in flow if s in ("dept", "office", "leader")]
        if steps and steps[0] != "dept":
            return TRANSITIONS.get((DRAFT, ACT_SUBMIT + "_skip_dept"))
    return None
