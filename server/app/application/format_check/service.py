"""格式校验应用服务：编排校验流程、记录与规则管理、审校工作台状态机。

审校工作台数据模型（迁移 009 起）：
- ``issues``        —— append-only 问题清单，每条带稳定整数 ``id``（= 生成时的下标）。
                       复检只追加新问题，永不删除/重排老条目。
- ``applied_ids``   —— 用户已「应用」的 issue id；每次复检后重置为 []。
- ``resolved_ids``  —— 经复检确认已修正的 issue id；累计保留。
- ``open_issue_count`` 为派生值：``len(issues) - len(resolved_ids)``，不落库。

原始上传文件 ``{id}.docx`` 全程只读，任何修正都重放到 ``*_preview.docx`` /
``*_current.docx`` / ``*_fixed.docx``，保证「原始文件永不被覆盖」。
"""
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from docx import Document as DocxDocument
from sqlalchemy.orm import Session

from app.application.format_check.check_engine import (
    FormatCheckEngine,
    extract_page_properties,
    extract_paragraph_properties,
)
from app.application.shared.writing_assistant import WritingAssistant
from app.core.config import settings
from app.core.exceptions import AppError, NotFoundError, PermissionDeniedError
from app.core.logging import get_logger
from app.domain.format_check.entities import (
    VALID_RULE_TARGETS,
    FormatCheckRecord,
    FormatRule,
)
from app.domain.identity.entities import ADMIN_OR_ABOVE, User
from app.infrastructure.repositories.format_check import (
    SqlAlchemyFormatCheckRecordRepository,
    SqlAlchemyFormatRuleRepository,
    load_id_list,
)

logger = get_logger(__name__)

SUPPORTED_SUFFIXES = ("docx", "txt", "md", "pdf")

# 记录关联的文件后缀（删除记录时一并清理）
_RECORD_FILE_SUFFIXES = ("", "_preview", "_current", "_fixed")


def _rule_to_dict(r: FormatRule) -> dict:
    return {
        "id": r.id, "name": r.name, "target": r.target, "checks": r.checks,
        "severity": r.severity, "is_default": r.is_default, "is_active": r.is_active,
        "remark": r.remark,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _open_issue_count(record: FormatCheckRecord) -> int:
    """未解决问题数 = 总问题数 - 已解决问题数（接口层派生，不落库）。"""
    issues = record.issues or []
    return max(len(issues) - len(set(load_id_list(record.resolved_ids))), 0)


def _record_brief(r: FormatCheckRecord) -> dict:
    return {
        "id": r.id, "filename": r.filename, "file_type": r.file_type,
        # issue_count 语义保持不变：累计总问题数（列表页与桌面端已消费）
        "issue_count": r.issue_count,
        "rule_issue_count": r.rule_issue_count,
        "ai_issue_count": r.ai_issue_count,
        "open_issue_count": _open_issue_count(r),
        "applied_ids": load_id_list(r.applied_ids),
        "resolved_ids": load_id_list(r.resolved_ids),
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


class FormatCheckService:
    def __init__(self, db: Session, assistant: Optional[WritingAssistant] = None) -> None:
        self.db = db
        self.rules = SqlAlchemyFormatRuleRepository(db)
        self.records = SqlAlchemyFormatCheckRecordRepository(db)
        self.engine = FormatCheckEngine(assistant)

    # ---- 校验文件存放（审阅/修正用，docx 保留，其他类型校验后即删） ----
    @property
    def check_dir(self) -> Path:
        d = settings.DATA_DIR / "format-check"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def record_file(self, record_id: str) -> Path:
        return self.check_dir / f"{record_id}.docx"

    # ================= issue id 稳定性（T3） =================
    def _ensure_issue_ids(self, record: FormatCheckRecord) -> bool:
        """存量老记录惰性补 id 并写回。

        - id 规则与新增记录完全一致：``enumerate(issues)`` 的下标（整数）。
        - 同时把 applied_ids / resolved_ids 初始化为 ``[]``（不能留 NULL，
          否则 open_issue_count 计算会 TypeError）。

        :return: 是否发生了写回。
        """
        issues = record.issues or []
        missing_id = any(
            not isinstance(it, dict) or it.get("id") is None for it in issues
        )
        missing_lists = record.applied_ids is None or record.resolved_ids is None
        if not missing_id and not missing_lists:
            return False

        for idx, it in enumerate(issues):
            if isinstance(it, dict):
                it["id"] = idx
        record.issues = issues
        if record.applied_ids is None:
            record.applied_ids = []
        if record.resolved_ids is None:
            record.resolved_ids = []

        logger.info(
            "格式校验记录 %s 缺少 issue id/工作台状态，已惰性补写（issues=%d）",
            record.id, len(issues),
        )
        self.records.update(record)
        return True

    def _load_record(self, record_id: str, user: User) -> FormatCheckRecord:
        """取记录并确保 issue id / 工作台状态可用。"""
        record = self.get_record_checked(record_id, user)
        self._ensure_issue_ids(record)
        return record

    # ================= 校验 =================
    async def check_upload(self, file, user: User, use_ai: bool = True,
                           rule_ids: Optional[str] = None) -> dict:
        filename = file.filename or "unnamed"
        suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        if suffix not in SUPPORTED_SUFFIXES:
            raise AppError(400, f"暂不支持 .{suffix} 文件的格式校验，请上传 Word(.docx) 文件")

        data = await file.read()
        if len(data) > settings.FORMAT_CHECK_MAX_SIZE:
            raise AppError(400, "文件超过大小限制")
        if not data:
            raise AppError(400, "文件为空")

        ids = [i for i in rule_ids.split(",") if i] if rule_ids else None
        rules = self.rules.list_for_check(ids)
        # 无配置规则不再阻塞校验：降级为纯 AI 校验模式
        ai_only = not rules
        if ai_only:
            if self.engine.assistant is None:
                raise AppError(503, "尚未配置格式规则，且 AI 服务不可用，暂时无法校验")
            use_ai = True
        rule_dicts = [_rule_to_dict(r) for r in rules]

        tmp_path = self.check_dir / f"{uuid.uuid4().hex}_{filename}"
        tmp_path.write_bytes(data)
        try:
            result = self.engine.check_file(tmp_path, filename, rule_dicts, use_ai=use_ai)
        except ValueError as e:
            tmp_path.unlink(missing_ok=True)
            raise AppError(400, str(e))
        except Exception as e:
            tmp_path.unlink(missing_ok=True)
            raise AppError(500, f"校验过程出错: {e}")

        issues = result["issues"]
        # 注入稳定整数 id（= 下标）。不用 uuid：复检后必须能与老条目对齐。
        for idx, issue in enumerate(issues):
            if isinstance(issue, dict):
                issue["id"] = idx

        record = self.records.add(FormatCheckRecord(
            user_id=user.id, filename=filename, file_type=result["file_type"],
            # B5'：快照必须带 severity，否则复检新增的问题会一律降级/升级为 error
            rule_snapshot=[{"id": r["id"], "name": r["name"], "target": r["target"],
                            "checks": r["checks"],
                            "severity": r.get("severity") or "error"}
                           for r in rule_dicts],
            issues=issues, issue_count=len(issues),
            rule_issue_count=len([i for i in issues if i["source"] == "rule"]),
            ai_issue_count=len([i for i in issues if i["source"] == "ai"]),
            applied_ids=[], resolved_ids=[],
        ))

        # docx 保留源文件（以记录ID命名），供审阅模式与自动修正使用；其他类型删除
        if result["file_type"] == "docx":
            tmp_path.replace(self.record_file(record.id))
        else:
            tmp_path.unlink(missing_ok=True)

        return {
            # 同一资源的 id 字段名统一：`id` 与 `record_id` 同值（为兼容两种客户端），
            # 与 GET /format-check/records 列表项的 `id` 对齐。
            "id": record.id,
            "record_id": record.id,
            "filename": filename,
            "file_type": result["file_type"],
            "ai_used": result["ai_used"],
            "check_mode": "ai_only" if ai_only else "rule",
            # issue_count 语义保持不变：累计总问题数
            "issue_count": len(issues),
            "open_issue_count": len(issues),
            "applied_ids": [],
            "resolved_ids": [],
            "issues": issues,
            "rules_used": [{"id": r["id"], "name": r["name"], "target": r["target"]}
                           for r in rule_dicts],
        }

    # ================= 记录 =================
    def list_records(self, user: User, page: int, page_size: int) -> dict:
        records, total = self.records.list_by_user(user.id, page, page_size)
        return {
            "total": total, "page": page, "page_size": page_size,
            "data": [_record_brief(r) for r in records],
        }

    def get_record_checked(self, record_id: str, user: User) -> FormatCheckRecord:
        record = self.records.get(record_id)
        if not record:
            raise NotFoundError("Record not found")
        if record.user_id != user.id and user.role not in ADMIN_OR_ABOVE:
            raise PermissionDeniedError("No permission")
        return record

    def get_record(self, record_id: str, user: User) -> dict:
        record = self._load_record(record_id, user)
        return {
            "id": record.id, "filename": record.filename, "file_type": record.file_type,
            "issues": record.issues, "issue_count": record.issue_count,
            "open_issue_count": _open_issue_count(record),
            "applied_ids": load_id_list(record.applied_ids),
            "resolved_ids": load_id_list(record.resolved_ids),
            "rule_snapshot": record.rule_snapshot,
            "created_at": record.created_at.isoformat() if record.created_at else None,
        }

    def delete_record(self, record_id: str, user: User) -> dict:
        """删除记录及其关联的全部文件（原始稿/预览稿/当前稿/修正稿）。

        单个文件删除失败（Windows 上被 Word / 杀毒软件占用很常见）只记 warning，
        不阻断记录删除——否则用户永远删不掉一条「文件被占用」的记录。
        """
        record = self.get_record_checked(record_id, user)
        removed: List[str] = []
        failed: List[str] = []
        for suffix in _RECORD_FILE_SUFFIXES:
            path = self.check_dir / f"{record.id}{suffix}.docx"
            if not path.exists():
                continue
            try:
                path.unlink()
                removed.append(path.name)
            except Exception as e:  # noqa: BLE001 - 文件清理失败绝不能阻断记录删除
                logger.warning("删除记录 %s 的关联文件 %s 失败（已忽略）: %s: %s",
                               record.id, path.name, type(e).__name__, e)
                failed.append(path.name)
        self.records.delete(record)
        logger.info("删除格式校验记录 %s，清理文件: %s", record.id, removed or "无")
        return {"id": record_id, "message": "记录已删除",
                "removed_files": removed, "failed_files": failed}

    # ================= 审阅模式 =================
    def _get_record_docx(self, record: FormatCheckRecord) -> Path:
        if record.file_type != "docx":
            raise AppError(400, "仅 Word(.docx) 文件支持审阅与自动修正")
        path = self.record_file(record.id)
        if not path.exists():
            raise AppError(410, "源文件已过期，请重新上传校验")
        return path

    @staticmethod
    def _read_doc_properties(path: Path) -> dict:
        """读取文档的段落排版属性 + 页面属性。"""
        doc = DocxDocument(str(path))
        return {
            "paragraphs": extract_paragraph_properties(doc),
            "page": extract_page_properties(doc),
        }

    def _build_current_doc(self, record: FormatCheckRecord,
                           applied: Optional[List[int]] = None) -> Path:
        """按已应用的 issue 从**原始文件**重放出「当前」文档。

        原始文件只读，结果写到 ``{id}_current.docx``。
        """
        src = self._get_record_docx(record)
        applied = load_id_list(applied if applied is not None else record.applied_ids)
        if not applied:
            return src
        out_path = self.check_dir / f"{record.id}_current.docx"
        self.engine.apply_fixes(src, record.issues or [], applied, out_path)
        return out_path

    def get_record_paragraphs(self, record_id: str, user: User,
                              version: str = "current") -> dict:
        """段落排版属性快照。

        :param version: ``original`` 读原始文件；``current`` 读已应用修正后的重放稿
                        （无已应用项时与 original 完全一致）。
        """
        record = self._load_record(record_id, user)
        if version == "original":
            path = self._get_record_docx(record)
        else:
            path = self._build_current_doc(record)
        data = self._read_doc_properties(path)
        data["version"] = version
        return data

    def preview_fix(self, record_id: str, accepted_indices: Optional[List[int]],
                    user: User) -> dict:
        record = self._load_record(record_id, user)
        if accepted_indices is None:
            accepted_indices = load_id_list(record.applied_ids)
        path = self._get_record_docx(record)
        out_path = self.check_dir / f"{record.id}_preview.docx"
        self.engine.apply_fixes(path, record.issues or [], accepted_indices, out_path)
        data = self._read_doc_properties(out_path)
        data["version"] = "preview"
        return data

    def fix_document(self, record_id: str, accepted_indices: Optional[List[int]],
                     user: User) -> Tuple[Path, str]:
        """生成修正稿。返回 (文件路径, 下载文件名)。

        accepted_indices 为 None 时使用持久化的 applied_ids，
        否则桌面端点「导出修正稿」会导出一份空修正。
        """
        record = self._load_record(record_id, user)
        if accepted_indices is None:
            accepted_indices = load_id_list(record.applied_ids)
        path = self._get_record_docx(record)
        out_path = self.check_dir / f"{record.id}_fixed.docx"
        self.engine.apply_fixes(path, record.issues or [], accepted_indices, out_path)
        return out_path, f"修正稿_{record.filename}"

    # ================= 工作台状态机（T6） =================
    @staticmethod
    def _issue_ids(issues: List[Dict]) -> List[int]:
        return [i.get("id") for i in issues
                if isinstance(i, dict) and i.get("id") is not None]

    def _workbench_payload(self, record: FormatCheckRecord) -> dict:
        """apply / undo 的统一响应体（不含 issues：这两个接口不改变 issues）。"""
        applied = load_id_list(record.applied_ids)
        resolved = load_id_list(record.resolved_ids)
        current = self._build_current_doc(record, applied)
        props = self._read_doc_properties(current)
        return {
            "id": record.id,
            "record_id": record.id,
            "applied_ids": applied,
            "resolved_ids": resolved,
            "issue_count": record.issue_count,
            "open_issue_count": _open_issue_count(record),
            "paragraphs": props["paragraphs"],
            "page": props["page"],
        }

    def apply_issue(self, record_id: str, issue_id: int, user: User) -> dict:
        """应用单条修正。未知 issue_id → 400 且不写库。"""
        try:
            issue_id = int(issue_id)
        except (TypeError, ValueError):
            raise AppError(400, "issue_id 必须是整数")
        record = self._load_record(record_id, user)
        known = set(self._issue_ids(record.issues or []))
        if issue_id not in known:
            # 必须拦截：否则垃圾 id 会被持久化，之后每次重放都带着它
            # detail 会原文展示给终端用户，因此用中文业务话术（id 仅供参考/排障）
            raise AppError(400, f"问题项不存在或已被处理（issue_id={issue_id}）")

        applied = sorted(set(load_id_list(record.applied_ids)) | {issue_id})
        record.applied_ids = applied
        self.records.update(record)
        return self._workbench_payload(record)

    def undo_issue(self, record_id: str, issue_id: int, user: User) -> dict:
        """撤销单条修正。未知 issue_id → 200 空操作（移除不存在元素本就是 no-op）。"""
        try:
            issue_id = int(issue_id)
        except (TypeError, ValueError):
            issue_id = -1
        record = self._load_record(record_id, user)
        applied = [i for i in load_id_list(record.applied_ids) if i != issue_id]
        record.applied_ids = applied
        self.records.update(record)
        return self._workbench_payload(record)

    def recheck(self, record_id: str, user: User) -> dict:
        """对「当前（已应用修正后）」的文档重跑规则检查，结果收敛回同一条记录。

        要点：
        - ``use_ai=False``；AI 类 issue（``fix_hint`` 为 None）不参与 resolved 判定。
        - issues 是 append-only：老条目 id/下标永不变，只追加新问题；
          「已修正」由 resolved_ids 表达。
        - 段落位移补偿：应用过 ``delete_paragraph`` 后后续段落下标会前移，
          匹配键用 ``paragraph_index - offset(p)``。
        - 复检后 applied_ids 重置为 []，resolved_ids 保留。
        """
        record = self._load_record(record_id, user)
        issues: List[Dict] = list(record.issues or [])
        applied = load_id_list(record.applied_ids)
        resolved = set(load_id_list(record.resolved_ids))

        applied_issues = [issues[i] for i in applied
                          if isinstance(i, int) and 0 <= i < len(issues)
                          and isinstance(issues[i], dict)]
        actionable = [i for i in issues if isinstance(i, dict) and i.get("fix_hint")]

        # 纯 AI 校验记录（无规则快照）或无任何可应用的规则问题 → 跳过复检
        if not record.rule_snapshot or not actionable:
            logger.info("记录 %s 无可复检的规则问题，跳过 recheck", record.id)
            return {
                "id": record.id, "record_id": record.id,
                "filename": record.filename, "file_type": record.file_type,
                "check_mode": "ai_only" if not record.rule_snapshot else "rule",
                "ai_used": False,
                "skipped_reason": "ai_only_record",
                "issue_count": len(issues),
                "open_issue_count": _open_issue_count(record),
                "applied_ids": load_id_list(record.applied_ids),
                "resolved_ids": sorted(resolved),
                "issues": issues,
                "rules_used": [{"id": r.get("id"), "name": r.get("name"),
                                "target": r.get("target")}
                               for r in (record.rule_snapshot or [])
                               if isinstance(r, dict)],
            }

        # 被删除的段落（原始下标），用于位移补偿
        deleted_idx = sorted({
            it["paragraph_index"] for it in applied_issues
            if (it.get("fix_hint") or {}).get("type") == "delete_paragraph"
            and it.get("paragraph_index") is not None
        })

        def offset(p: int) -> int:
            """原始下标 p 之前被删除的段落数。"""
            return sum(1 for d in deleted_idx if d < p)

        def match_key(it: Dict, mapped_index: Optional[int]) -> Tuple:
            hint = it.get("fix_hint") or {}
            value = hint.get("value")
            return (mapped_index, it.get("element"), hint.get("type"),
                    hint.get("field"), str(value) if value is not None else None)

        # 老问题：把原始下标换算到当前文档坐标系
        old_keys: Dict[Tuple, int] = {}
        for it in issues:
            if not isinstance(it, dict) or not it.get("fix_hint"):
                continue
            p = it.get("paragraph_index")
            mapped = (p - offset(p)) if p is not None else None
            old_keys.setdefault(match_key(it, mapped), it.get("id"))

        # 老快照可能缺 severity（B5'），补兜底，避免复检新增问题一律变 error
        rules = [{**r, "severity": (r.get("severity") or "error")}
                 for r in (record.rule_snapshot or []) if isinstance(r, dict)]

        doc_path = self._build_current_doc(record, applied)
        result = self.engine.check_file(doc_path, record.filename, rules, use_ai=False)
        new_issues: List[Dict] = result.get("issues", [])
        new_keys = {match_key(it, it.get("paragraph_index"))
                    for it in new_issues if isinstance(it, dict)}

        # 老问题若在复检结果中消失 → 标记已解决
        for key, issue_id in old_keys.items():
            if key not in new_keys and issue_id is not None:
                resolved.add(int(issue_id))

        # 新问题才追加，id 从 len(issues) 继续；老条目 id 永不变
        next_id = len(issues)
        added: List[Dict] = []
        for it in new_issues:
            if not isinstance(it, dict):
                continue
            if match_key(it, it.get("paragraph_index")) in old_keys:
                continue
            item = dict(it)
            item["id"] = next_id
            next_id += 1
            added.append(item)
        if added:
            issues = issues + added

        record.issues = issues
        record.issue_count = len(issues)
        record.rule_issue_count = len(
            [i for i in issues if isinstance(i, dict) and i.get("source") == "rule"])
        record.ai_issue_count = len(
            [i for i in issues if isinstance(i, dict) and i.get("source") == "ai"])
        record.applied_ids = []           # 复检后重置
        record.resolved_ids = sorted(resolved)
        self.records.update(record)

        logger.info(
            "记录 %s 复检完成：新增 %d 条，累计已解决 %d 条，applied_ids 已重置",
            record.id, len(added), len(record.resolved_ids),
        )
        return {
            "id": record.id, "record_id": record.id,
            "filename": record.filename, "file_type": record.file_type,
            "check_mode": "rule",
            "ai_used": False,
            "issue_count": len(issues),
            "open_issue_count": _open_issue_count(record),
            "applied_ids": [],
            "resolved_ids": record.resolved_ids,
            "added_count": len(added),
            "issues": issues,
            "rules_used": [{"id": r.get("id"), "name": r.get("name"),
                            "target": r.get("target")} for r in rules],
        }

    # ================= 规则管理 =================
    def list_rules(self) -> List[dict]:
        return [_rule_to_dict(r) for r in self.rules.list_active()]

    def create_rule(self, req, admin: User) -> dict:
        if req.target not in VALID_RULE_TARGETS:
            raise AppError(400, f"target 必须是: {', '.join(VALID_RULE_TARGETS)}")
        rule = self.rules.add(FormatRule(
            name=req.name, target=req.target, checks=req.checks,
            severity=req.severity, is_default=req.is_default,
            is_active=req.is_active, remark=req.remark, created_by=admin.id,
        ))
        return {"id": rule.id, "message": "规则已创建"}

    def update_rule(self, rule_id: str, req) -> dict:
        if req.target not in VALID_RULE_TARGETS:
            raise AppError(400, f"target 必须是: {', '.join(VALID_RULE_TARGETS)}")
        rule = self.rules.get(rule_id)
        if not rule:
            raise NotFoundError("Rule not found")
        rule.name = req.name
        rule.target = req.target
        rule.checks = req.checks
        rule.severity = req.severity
        rule.is_default = req.is_default
        rule.is_active = req.is_active
        rule.remark = req.remark
        self.rules.update(rule)
        return {"message": "规则已更新"}

    def delete_rule(self, rule_id: str) -> dict:
        rule = self.rules.get(rule_id)
        if not rule:
            raise NotFoundError("Rule not found")
        self.rules.hard_delete(rule)
        return {"message": "规则已删除"}
