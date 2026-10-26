"""格式校验工作台：各按钮链路的服务端契约（应用 / 撤销 / 复检 / 导出 / 规则 AI 生成）。

覆盖桌面端「审校工作台」与「规则管理」上每个按钮实际依赖的服务端行为：

| 按钮             | 接口                                   | 本文件对应用例                     |
|------------------|----------------------------------------|------------------------------------|
| 上传校验         | POST /format-check/check                | test_rule_hits_and_ai_issues       |
| 应用修改         | POST /records/{id}/apply                | test_apply_issue_changes_docx      |
| 撤销             | POST /records/{id}/undo                 | test_undo_reverts_applied_issue    |
| 重新校验         | POST /records/{id}/recheck              | test_recheck_keeps_applied_fixes   |
| 导出修正稿       | POST /format-check/fix                  | test_export_keeps_fixes_after_recheck |
| 保存修改         | PUT /records/{id}/content               | test_manual_edit_becomes_new_baseline |
| AI 生成校验项    | POST /rules/compile                     | test_compile_rule_*                |
| 保存规则         | POST /rules                             | test_custom_rule_participates_in_check |

不启 HTTP、不打真实模型：AI 用可控桩（_Assistant），保证用例稳定且能触发边界。
"""
import asyncio
import json
from pathlib import Path

import pytest
from docx import Document
from docx.shared import Pt

from app.application.format_check.service import FormatCheckService
from app.core.exceptions import AppError
from app.domain.format_check.entities import FormatRule
from app.domain.identity.entities import ROLE_DEVELOPER, User
from app.infrastructure.database.base import Base
from app.infrastructure.database.models.format_check import (
    FormatCheckRecordModel,
    FormatRuleModel,
)
from app.infrastructure.database.session import SessionLocal, engine
from app.infrastructure.repositories.format_check import (
    SqlAlchemyFormatRuleRepository,
)

Base.metadata.create_all(bind=engine)

ADMIN = User(username="fcadmin", email="fc@test.local", hashed_password="x",
             id="u-fc-1", role=ROLE_DEVELOPER)
USER = User(username="fcuser", email="fcu@test.local", hashed_password="x",
            id="u-fc-2")

BODY_RULE_CHECKS = {
    "font_name": "仿宋_GB2312",
    "font_size_pt": 16,
    "alignment": "justify",
    "first_line_indent_chars": 2,
    "line_spacing_pt": 28,
}


# ---------------- 测试替身 ----------------

class _File:
    """最小 UploadFile 替身：只要 filename 与 read()。"""

    def __init__(self, path: Path, filename: str = "公文.docx") -> None:
        self.filename = filename
        self._data = path.read_bytes()

    async def read(self) -> bytes:
        return self._data


class _Assistant:
    """AI 桩：按 queue 依次返回内容，并记录每次调用，便于断言「AI 确实被调用」。

    reply=None 表示模拟 AI 不可用（返回空串，与真实网关失败行为一致）。
    """

    def __init__(self, *replies) -> None:
        self.replies = list(replies)
        self.calls = []

    def complete(self, messages, temperature=0.1, max_tokens=512):
        self.calls.append({"messages": messages, "temperature": temperature,
                           "max_tokens": max_tokens})
        if not self.replies:
            return ""
        r = self.replies.pop(0)
        return r if r is not None else ""


# ---------------- 素材构造 ----------------

def _make_docx(path: Path) -> Path:
    """造一份明显不合规的公文：正文宋体 12 磅、无缩进、左对齐、含不规范表达。"""
    doc = Document()
    p0 = doc.add_paragraph("关于开展2026年度法治宣传工作的通知")
    p0.runs[0].font.name = "宋体"
    p0.runs[0].font.size = Pt(22)

    for text in ("我局截止目前已完成阶段性摸排工作。",
                 "现将有关事项通知如下，请各单位遵照执行。"):
        p = doc.add_paragraph(text)
        p.runs[0].font.name = "宋体"
        p.runs[0].font.size = Pt(12)

    p = doc.add_paragraph("广州市白云区司法局")
    p.runs[0].font.name = "宋体"
    p.runs[0].font.size = Pt(12)
    p = doc.add_paragraph("2026年10月5日")
    p.runs[0].font.name = "宋体"
    p.runs[0].font.size = Pt(12)
    doc.save(str(path))
    return path


def _font_pt_of(docx_path: Path, index: int):
    """读某段的实际字号（磅），校验「修正是否真的写进了 docx」。"""
    doc = Document(str(docx_path))
    run = doc.paragraphs[index].runs[0]
    return run.font.size.pt if run.font.size else None


def _rule(db, name="正文格式", target="body", checks=None, is_default=True,
          is_active=True) -> FormatRule:
    return SqlAlchemyFormatRuleRepository(db).add(FormatRule(
        name=name, target=target, checks=checks if checks is not None else dict(BODY_RULE_CHECKS),
        severity="error", is_default=is_default, is_active=is_active,
        remark="测试规则", created_by=ADMIN.id,
    ))


def _check(svc: FormatCheckService, docx_path: Path, user=ADMIN, use_ai=False):
    return asyncio.run(svc.check_upload(
        _File(docx_path, docx_path.name), user, use_ai=use_ai))


def _ensure_user(db, user: User) -> None:
    """format_rules.created_by / records.user_id 都是外键，测试里得有真实用户行。"""
    from app.infrastructure.database.models.identity import UserModel

    if db.get(UserModel, user.id) is None:
        db.add(UserModel(id=user.id, username=user.username, email=user.email,
                         hashed_password=user.hashed_password, role=user.role,
                         is_active=True))
        db.commit()


@pytest.fixture()
def env(tmp_path):
    db = SessionLocal()
    try:
        _ensure_user(db, ADMIN)
        _ensure_user(db, USER)
        svc = FormatCheckService(db, None, None)
        yield db, svc, tmp_path
        for f in svc.check_dir.glob("*"):
            try:
                f.unlink()
            except OSError:
                pass
        # 规则 / 记录是模块级库里的持久数据：不清会把「无规则」类用例污染成有规则
        db.query(FormatCheckRecordModel).delete()
        db.query(FormatRuleModel).delete()
        db.commit()
    finally:
        db.close()


# ---------------- 上传校验 ----------------

def test_rule_hits_are_reported(env):
    """上传 .docx：规则命中项必须出现，且带可自动修正的 fix_hint。"""
    db, svc, tmp = env
    _rule(db)
    doc = _make_docx(tmp / "a.docx")

    res = _check(svc, doc)

    assert res["file_type"] == "docx"
    assert res["check_mode"] == "rule"
    kinds = {(i["element"], i["source"]) for i in res["issues"]}
    assert ("字号", "rule") in kinds
    assert ("字体", "rule") in kinds
    assert ("首行缩进", "rule") in kinds
    # 内容确定性检查不依赖模型也必须执行（"截止目前" → 规范为"截至目前"）
    assert any(i["element"] == "时间表述" for i in res["issues"])
    # 每条规则问题都要能自动修正，否则界面上不会给「应用修改」按钮
    assert all(i["fix_hint"] for i in res["issues"] if i["source"] == "rule")
    # id 必须连续可索引：apply 时把 id 当 issues 下标用
    assert [i["id"] for i in res["issues"]] == list(range(len(res["issues"])))


def test_body_rule_does_not_mislabel_signature_and_date(env):
    db, svc, tmp = env
    _rule(db, name="正文字号", checks={"font_size_pt": 16})
    res = _check(svc, _make_docx(tmp / "body-only.docx"))
    assert not any(issue["element"] == "字号" and issue["paragraph_index"] in (3, 4)
                   for issue in res["issues"])


def test_body_font_rule_uses_paragraph_style_and_font_family(env):
    db, svc, tmp = env
    from docx import Document
    from docx.shared import Pt
    _rule(db, name="正文样式字体", checks={"font_name": "仿宋_GB2312", "font_size_pt": 16})
    doc = Document()
    doc.styles["Normal"].font.name = "仿宋"
    doc.styles["Normal"].font.size = Pt(16)
    doc.add_paragraph("标题")
    doc.add_paragraph("正文使用段落样式设置字体字号。")
    path = tmp / "style-font.docx"
    doc.save(str(path))
    res = _check(svc, path)
    assert not any(issue["element"] in ("字体", "字号") and issue["paragraph_index"] == 1
                   for issue in res["issues"])


def test_mixed_runs_cannot_hide_font_or_size_errors(env):
    db, svc, tmp = env
    doc = Document()
    doc.add_paragraph("标题")
    body = doc.add_paragraph()
    good = body.add_run("前半段格式正确。")
    good.font.name = "仿宋"
    good.font.size = Pt(16)
    bad = body.add_run("后半段字体字号错误。")
    bad.font.name = "宋体"
    bad.font.size = Pt(12)
    path = tmp / "mixed-runs.docx"
    doc.save(path)
    result = svc.engine.check_file(path, path.name, [{
        "target": "body", "checks": {"font_name": "仿宋", "font_size_pt": 16},
    }], use_ai=False)
    assert {issue["element"] for issue in result["issues"]} == {"字体", "字号"}
    assert all(issue["paragraph_index"] == 1 for issue in result["issues"])


def test_title_after_blank_paragraph_keeps_correct_fix_location(env):
    db, svc, tmp = env
    doc = Document()
    doc.add_paragraph("")
    title = doc.add_paragraph("标题")
    title.runs[0].font.size = Pt(12)
    path = tmp / "leading-blank.docx"
    doc.save(path)
    result = svc.engine.check_file(path, path.name, [{
        "target": "title", "checks": {"font_size_pt": 22},
    }], use_ai=False)
    assert len(result["issues"]) == 1
    assert result["issues"][0]["paragraph_index"] == 1


def test_recheck_uses_new_and_edited_personal_rules(env):
    db, svc, tmp = env
    checked = _check(svc, _make_docx(tmp / "new-rule.docx"))
    rule = _rule(db, name="个人新规则", checks={"font_size_pt": 20}, is_default=False)
    result = svc.recheck(checked["id"], ADMIN)
    assert rule.id in {item["id"] for item in result["rules_used"]}
    assert any(issue["element"] == "字号" and issue["expected"] == "20磅"
               for issue in result["issues"])
    rule.checks = {"font_size_pt": 24}
    svc.rules.update(rule)
    result = svc.recheck(checked["id"], ADMIN)
    assert any(issue["element"] == "字号" and issue["expected"] == "24磅"
               and issue["id"] not in result["resolved_ids"] for issue in result["issues"])


def test_ai_issues_are_merged_and_counted(env):
    """勾选 AI 时：AI 审校结果与规则结果合并，ai_issue_count 正确。"""
    db, svc, tmp = env
    db_svc = FormatCheckService(db, _Assistant(json.dumps([
        {"location": "第2段", "paragraph_index": 1, "element": "称谓",
         "current": "我局", "expected": "区司法局", "suggestion": "写明全称"},
    ], ensure_ascii=False)), None)
    _rule(db)
    doc = _make_docx(tmp / "ai.docx")

    res = _check(db_svc, doc, use_ai=True)

    assert res["ai_used"] is True
    assert res["check_mode"] == "hybrid"
    assert len([i for i in res["issues"] if i["source"] == "ai"]) == 1
    assert any(i["source"] == "ai" and i["element"] == "称谓" for i in res["issues"])
    # 落库时 ai/rule 分别计数（列表页与统计展示依赖）
    assert db_svc.records.get(res["id"]).ai_issue_count == 1


def test_ai_prompt_uses_real_paragraph_index(env):
    """AI 拿到的段号必须是真实段落下标。

    文档里夹空段时，若按「非空行」重新编号，AI 报的段号会整体前移，
    界面「定位第 N 段」与复检的匹配键都会跟着错位。
    """
    db, svc, tmp = env
    assistant = _Assistant("[]")
    db_svc = FormatCheckService(db, assistant, None)
    _rule(db)
    doc = _make_docx(tmp / "idx.docx")
    docx = Document(str(doc))
    # 在第 1 段后插一个空段：后续正文的真实下标整体 +1
    docx.paragraphs[0].insert_paragraph_before("")
    docx.save(str(doc))

    _check(db_svc, doc, use_ai=True)

    prompt = assistant.calls[0]["messages"][-1]["content"]
    # 空段之后的正文从第 3 段起算（标题 1、空段 2），而不是被压成第 2 段
    assert "[第3段] 我局截止目前已完成阶段性摸排工作。" in prompt


def test_missing_rule_rows_are_seeded_from_national_standard(env):
    """新账号无需管理员手工播种，首次校验即使用国标预置规则。"""
    db, svc, tmp = env
    db_svc = FormatCheckService(db, _Assistant("[]"), None)
    doc = _make_docx(tmp / "b.docx")

    res = _check(db_svc, doc, use_ai=False)

    assert res["check_mode"] == "rule"
    assert res["rules_used"]
    # 内容确定性检查仍然执行
    assert any(i["element"] == "时间表述" for i in res["issues"])


def test_default_rules_work_without_ai(env):
    """国标预置规则不依赖 AI 可用性。"""
    db, svc, tmp = env
    doc = _make_docx(tmp / "c.docx")
    res = _check(svc, doc)
    assert res["rules_used"]
    assert res["check_mode"] == "rule"


def test_unsupported_suffix_is_rejected(env):
    """.doc（老二进制格式）不在支持列表，必须 400 而不是 500。"""
    db, svc, tmp = env
    bad = tmp / "legacy.doc"
    bad.write_bytes(b"\xd0\xcf\x11\xe0")
    with pytest.raises(AppError) as e:
        _check(svc, bad)
    assert e.value.status_code == 400
    assert "暂不支持" in str(e.value.detail)


# ---------------- 应用 / 撤销 ----------------

def test_apply_issue_changes_docx(env):
    """点「应用修改」：当前稿必须真的被改写（不是只改数据库标记）。"""
    db, svc, tmp = env
    _rule(db)
    doc = _make_docx(tmp / "d.docx")
    res = _check(svc, doc)
    target = next(i for i in res["issues"] if i["element"] == "字号"
                  and i["paragraph_index"] == 1)

    assert _font_pt_of(svc.record_file(res["id"]), 1) == 12.0
    out = svc.apply_issue(res["id"], target["id"], ADMIN)

    assert target["id"] in out["applied_ids"]
    current = svc._build_current_doc(svc.records.get(res["id"]))
    assert _font_pt_of(current, 1) == 16.0


def test_apply_unknown_issue_id_is_rejected(env):
    """越界 / 垃圾 issue_id 必须 400，不能被持久化进去污染后续重放。"""
    db, svc, tmp = env
    _rule(db)
    doc = _make_docx(tmp / "e.docx")
    res = _check(svc, doc)

    with pytest.raises(AppError) as e:
        svc.apply_issue(res["id"], 9999, ADMIN)
    assert e.value.status_code == 400


def test_undo_reverts_applied_issue(env):
    """点「撤销」：从 applied_ids 移除，当前稿回到未修正状态。"""
    db, svc, tmp = env
    _rule(db)
    doc = _make_docx(tmp / "f.docx")
    res = _check(svc, doc)
    target = next(i for i in res["issues"] if i["element"] == "字号"
                  and i["paragraph_index"] == 1)

    svc.apply_issue(res["id"], target["id"], ADMIN)
    out = svc.undo_issue(res["id"], target["id"], ADMIN)

    assert out["applied_ids"] == []
    current = svc._build_current_doc(svc.records.get(res["id"]))
    assert _font_pt_of(current, 1) == 12.0


def test_undo_clears_resolved_flag(env):
    """撤销已复检确认的修正时，「已修正」标记必须一起摘掉。

    否则界面显示「已修正 ✓」，文档里却已经被撤掉，状态自相矛盾。
    """
    db, svc, tmp = env
    _rule(db)
    doc = _make_docx(tmp / "f2.docx")
    res = _check(svc, doc)
    target = next(i for i in res["issues"] if i["element"] == "字号"
                  and i["paragraph_index"] == 1)

    svc.apply_issue(res["id"], target["id"], ADMIN)
    svc.recheck(res["id"], ADMIN)
    out = svc.undo_issue(res["id"], target["id"], ADMIN)

    assert out["applied_ids"] == []
    assert out["resolved_ids"] == []


def test_undo_unknown_issue_id_is_noop(env):
    """撤销不存在的 id 是空操作（200），不能报错。"""
    db, svc, tmp = env
    _rule(db)
    doc = _make_docx(tmp / "g.docx")
    res = _check(svc, doc)
    out = svc.undo_issue(res["id"], 4242, ADMIN)
    assert out["applied_ids"] == []


# ---------------- 复检 / 导出 ----------------

def test_recheck_marks_fixed_issues_resolved(env):
    """点「重新校验」：已应用且修正生效的问题应进入 resolved_ids。"""
    db, svc, tmp = env
    _rule(db)
    doc = _make_docx(tmp / "h.docx")
    res = _check(svc, doc)
    target = next(i for i in res["issues"] if i["element"] == "字号"
                  and i["paragraph_index"] == 1)

    svc.apply_issue(res["id"], target["id"], ADMIN)
    out = svc.recheck(res["id"], ADMIN)

    assert target["id"] in out["resolved_ids"]
    assert out["open_issue_count"] < out["issue_count"]


def test_recheck_keeps_applied_fixes(env):
    """复检后当前稿仍应保留已应用的修正。

    复检只是「确认修正是否生效」，不能把修改悄悄丢掉：applied_ids 重置为 []
    后，_build_current_doc 从原始文件重放空集合会得到未修改的原文。
    """
    db, svc, tmp = env
    _rule(db)
    doc = _make_docx(tmp / "i.docx")
    res = _check(svc, doc)
    target = next(i for i in res["issues"] if i["element"] == "字号"
                  and i["paragraph_index"] == 1)

    svc.apply_issue(res["id"], target["id"], ADMIN)
    svc.recheck(res["id"], ADMIN)

    current = svc._build_current_doc(svc.records.get(res["id"]))
    assert _font_pt_of(current, 1) == 16.0


def test_export_keeps_fixes_after_recheck(env):
    """「导出修正稿」在复检之后也必须带修正（桌面端不传 accepted_indices）。"""
    db, svc, tmp = env
    _rule(db)
    doc = _make_docx(tmp / "j.docx")
    res = _check(svc, doc)
    target = next(i for i in res["issues"] if i["element"] == "字号"
                  and i["paragraph_index"] == 1)

    svc.apply_issue(res["id"], target["id"], ADMIN)
    svc.recheck(res["id"], ADMIN)
    out_path, name = svc.fix_document(res["id"], None, ADMIN)

    assert name.startswith("修正稿_")
    assert _font_pt_of(out_path, 1) == 16.0


def test_export_without_applied_returns_source(env):
    """没应用任何修正时导出：返回文档仍可打开，不报错。"""
    db, svc, tmp = env
    _rule(db)
    doc = _make_docx(tmp / "k.docx")
    res = _check(svc, doc)
    out_path, _ = svc.fix_document(res["id"], None, ADMIN)
    assert out_path.exists()


# ---------------- 人工保存 ----------------

def test_manual_edit_becomes_new_baseline(env):
    """点「保存修改」：正文写回源文件成为新基线，应用/解决状态重置。"""
    db, svc, tmp = env
    _rule(db)
    doc = _make_docx(tmp / "l.docx")
    res = _check(svc, doc)
    target = next(i for i in res["issues"] if i["element"] == "字号"
                  and i["paragraph_index"] == 1)
    svc.apply_issue(res["id"], target["id"], ADMIN)

    out = svc.update_record_content(
        res["id"], ["标题行", "改写后的第一段。", "改写后的第二段。"], ADMIN)

    assert out["applied_ids"] == []
    assert out["resolved_ids"] == []
    saved = Document(str(svc.record_file(res["id"])))
    assert saved.paragraphs[1].text == "改写后的第一段。"


def test_manual_edit_rejects_empty_body(env):
    db, svc, tmp = env
    _rule(db)
    doc = _make_docx(tmp / "m.docx")
    res = _check(svc, doc)
    with pytest.raises(AppError) as e:
        svc.update_record_content(res["id"], ["", "   "], ADMIN)
    assert e.value.status_code == 400


def test_manual_formatting_is_written_to_source_docx_and_recheckable(env):
    db, svc, tmp = env
    doc = _make_docx(tmp / "styled.docx")
    res = _check(svc, doc)
    original = Document(str(svc.record_file(res["id"])))
    texts = [p.text for p in original.paragraphs]
    svc.update_record_content(res["id"], texts, ADMIN, {
        "1": {"font_name": "黑体", "font_size_pt": 18,
              "bold": True, "alignment": "center"},
    })
    saved = Document(str(svc.record_file(res["id"])))
    assert saved.paragraphs[1].runs[0].font.name == "黑体"
    assert saved.paragraphs[1].runs[0].font.size.pt == 18
    assert saved.paragraphs[1].runs[0].bold is True
    assert saved.paragraphs[1].alignment == 1  # WD_ALIGN_PARAGRAPH.CENTER
    assert svc.recheck(res["id"], ADMIN)["id"] == res["id"]


def test_manual_inline_bold_is_exported_as_word_runs(env):
    _db, svc, tmp = env
    res = _check(svc, _make_docx(tmp / "inline-bold.docx"))
    original = Document(str(svc.record_file(res["id"])))
    texts = [p.text for p in original.paragraphs]
    texts[1] = "请突出**重点事项**并核对。"
    svc.update_record_content(res["id"], texts, ADMIN)
    saved = Document(str(svc.record_file(res["id"])))
    paragraph = saved.paragraphs[1]
    assert paragraph.text == "请突出重点事项并核对。"
    assert any(run.text == "重点事项" and run.bold for run in paragraph.runs)


# ---------------- 规则管理（AI 生成 + 生效） ----------------

class _CompileReq:
    def __init__(self, target, description, name=None):
        self.target = target
        self.description = description
        self.name = name


def test_compile_rule_filters_unknown_keys(env):
    """AI 返回里的未知键必须被白名单丢弃，只留下引擎认识的校验项。"""
    db, svc, tmp = env
    svc.engine.assistant = _Assistant(json.dumps({
        "name": "正文格式",
        "checks": {"font_size_pt": 16, "font_name": "仿宋_GB2312",
                   "invented_key": "危险值", "alignment": "两端对齐"},
    }, ensure_ascii=False))

    out = svc.compile_rule(_CompileReq("body", "正文用仿宋三号字，两端对齐"), ADMIN)

    assert out["checks"] == {"font_size_pt": 16.0, "font_name": "仿宋_GB2312",
                             "alignment": "justify"}
    assert any("字号" in s for s in out["summary"])


def test_compile_rule_rejects_unrecognisable_description(env):
    """描述无法映射到任何校验项 → 400 且给出可照做的例子，不能保存空规则。"""
    db, svc, tmp = env
    svc.engine.assistant = _Assistant(json.dumps({"name": "x", "checks": {"随便": 1}},
                                                 ensure_ascii=False))
    with pytest.raises(AppError) as e:
        svc.compile_rule(_CompileReq("body", "把文章写得好看一点"), ADMIN)
    assert e.value.status_code == 400
    assert "例如" in str(e.value.detail)


def test_compile_rule_reports_ai_failure(env):
    """AI 失败时，明确写出的硬格式仍应识别，避免规则按钮看似失效。"""
    db, svc, tmp = env
    svc.engine.assistant = _Assistant(None)
    out = svc.compile_rule(_CompileReq(
        "body", "正文用仿宋小三号，固定行距28磅，首行缩进2字符，两端对齐"), ADMIN)
    assert out["checks"] == {
        "font_name": "仿宋", "font_size_pt": 15.0, "alignment": "justify",
        "line_spacing_pt": 28.0, "first_line_indent_chars": 2.0,
    }
    assert out["recognition"] == "literal"

    svc.engine.assistant = _Assistant("这不是 JSON")
    out = svc.compile_rule(_CompileReq("page", "上边距3.7厘米，下边距3.5厘米"), ADMIN)
    assert out["checks"] == {"top_margin_cm": 3.7, "bottom_margin_cm": 3.5}


def test_compile_rule_literal_items_complete_partial_ai_result(env):
    db, svc, tmp = env
    svc.engine.assistant = _Assistant(json.dumps({
        "name": "正文格式", "checks": {"font_name": "仿宋"},
    }, ensure_ascii=False))
    out = svc.compile_rule(_CompileReq(
        "body", "正文仿宋三号，固定行距28磅，首行缩进2字符，两端对齐"), ADMIN)
    assert out["checks"] == {
        "font_name": "仿宋", "font_size_pt": 16.0, "alignment": "justify",
        "line_spacing_pt": 28.0, "first_line_indent_chars": 2.0,
    }


def test_compile_rule_reports_requirements_outside_selected_target(env):
    db, svc, tmp = env
    svc.engine.assistant = _Assistant(json.dumps({
        "checks": {"font_size_pt": 16},
        "unsupported": ["上边距请在页面设置规则中配置"],
    }, ensure_ascii=False))
    output = svc.compile_rule(_CompileReq("body", "正文三号，上边距3.7厘米"), ADMIN)
    assert output["checks"]["font_size_pt"] == 16
    assert output["warnings"] == ["上边距请在页面设置规则中配置"]


def test_negated_font_instruction_does_not_override_ai_interpretation(env):
    db, svc, tmp = env
    svc.engine.assistant = _Assistant(json.dumps({
        "checks": {"font_name": "黑体", "font_size_pt": 16},
    }, ensure_ascii=False))
    output = svc.compile_rule(_CompileReq("body", "不要仿宋，正文改为黑体三号"), ADMIN)
    assert output["checks"] == {"font_name": "黑体", "font_size_pt": 16.0}


def test_compile_rule_rejects_bad_target(env):
    db, svc, tmp = env
    svc.engine.assistant = _Assistant("{}")
    with pytest.raises(AppError) as e:
        svc.compile_rule(_CompileReq("不存在的对象", "随便"), ADMIN)
    assert e.value.status_code == 400


def test_custom_rule_participates_in_check(env):
    """保存后的自定义规则必须真的参与校验。

    桌面端新建规则的「默认规则」复选框默认未勾选（is_default=false），
    若服务端只取 is_default=true 的规则，用户新建的规则会静默不生效。
    """
    db, svc, tmp = env
    svc.engine.assistant = _Assistant(json.dumps(
        {"name": "正文三号字", "checks": {"font_size_pt": 16}}, ensure_ascii=False))
    compiled = svc.compile_rule(_CompileReq("body", "正文用三号字"), ADMIN)

    class _Req:
        target = "body"
        name = compiled["name"]
        checks = compiled["checks"]
        severity = "error"
        is_default = False      # 与桌面端新建规则未勾选「默认规则」一致
        is_active = True
        remark = "正文用三号字"

    svc.create_rule(_Req(), ADMIN)
    doc = _make_docx(tmp / "n.docx")

    res = _check(svc, doc)

    assert any(i["element"] == "字号" and i["source"] == "rule" for i in res["issues"])
    assert res["check_mode"] == "rule"


def test_rules_are_seeded_per_user_and_disabled_rule_can_be_reenabled(env):
    db, svc, tmp = env
    admin_rules = svc.list_rules(ADMIN)
    user_rules = svc.list_rules(USER)
    assert admin_rules and user_rules
    assert all(rule["is_default"] for rule in user_rules)
    assert {rule["id"] for rule in admin_rules}.isdisjoint(
        {rule["id"] for rule in user_rules})

    selected = next(rule for rule in user_rules if rule["target"] == "body")
    svc.set_rule_active(selected["id"], False, USER)
    inactive = next(rule for rule in svc.list_rules(USER) if rule["id"] == selected["id"])
    assert inactive["is_active"] is False
    assert selected["id"] not in {
        rule.id for rule in svc.rules.list_for_check(USER.id, None)}
    assert selected["id"] not in {
        rule.id for rule in svc.rules.list_for_check(ADMIN.id, None)}
    svc.set_rule_active(selected["id"], True, USER)
    assert selected["id"] in {
        rule.id for rule in svc.rules.list_for_check(USER.id, None)}


def test_ppt_preset_toggle_affects_generated_deck_quality(env):
    from app.application.ppt.service import PPTService
    from pptx import Presentation
    from io import BytesIO

    db, svc, tmp = env
    prs = Presentation()
    for _ in range(2):
        prs.slides.add_slide(prs.slide_layouts[6])
    output = BytesIO()
    prs.save(output)
    data = output.getvalue()
    ppt = PPTService(db, None)
    rules = ppt.active_quality_rules(USER.id)
    assert any("页数不符" in issue for issue in
               ppt.assess_generated_pptx(data, 3, rules))
    page_rule = next(rule for rule in svc.list_rules(USER)
                     if rule["target"] == "ppt" and rule["checks"].get("check_page_count"))
    svc.set_rule_active(page_rule["id"], False, USER)
    assert not any("页数不符" in issue for issue in
                   ppt.assess_generated_pptx(data, 3, ppt.active_quality_rules(USER.id)))


def test_custom_ppt_quality_rule_is_blocking(env):
    db, svc, tmp = env

    class _Req:
        target = "ppt"
        name = "每页文字数量"
        checks = {"max_chars_per_slide": 120}
        severity = "warning"
        is_active = True
        remark = "个人 PPT 规则"

    created = svc.create_rule(_Req(), USER)
    rule = next(item for item in svc.list_rules(USER) if item["id"] == created["id"])
    assert rule["severity"] == "error"


def test_all_format_rules_disabled_still_allows_manual_check(env):
    db, svc, tmp = env
    for rule in svc.list_rules(USER):
        if rule["target"] != "ppt":
            svc.set_rule_active(rule["id"], False, USER)
    doc = _make_docx(tmp / "all-disabled.docx")
    import asyncio
    data = doc.read_bytes()

    class _File:
        filename = "all-disabled.docx"

        async def read(self):
            return data

    result = asyncio.run(svc.check_upload(_File(), USER, use_ai=False))
    assert result["rules_used"] == []
    assert result["ai_used"] is False
    assert not any(issue["current"] == "截止目前" for issue in result["issues"])


def test_disabled_rule_stops_reporting_on_recheck(env):
    db, svc, tmp = env
    rule = _rule(db, name="停用复检测试", target="content",
                 checks={"forbidden_words": ["专用测试词"]}, is_default=False)
    doc = _make_docx(tmp / "disable-recheck.docx")
    from docx import Document
    document = Document(str(doc))
    document.add_paragraph("专用测试词")
    document.save(str(doc))
    checked = _check(svc, doc)
    issue = next(item for item in checked["issues"] if item["element"] == "禁用词"
                 and item["current"] == "专用测试词")
    svc.set_rule_active(rule.id, False, ADMIN)
    rechecked = svc.recheck(checked["id"], ADMIN)
    assert issue["id"] in rechecked["resolved_ids"]


def test_user_custom_rules_do_not_leak_to_other_user(env):
    db, svc, tmp = env

    class _Req:
        target = "content"
        name = "个人禁用词"
        checks = {"forbidden_words": ["测试专用词"]}
        severity = "warning"
        is_default = True
        is_active = True
        remark = "个人规则"

    created = svc.create_rule(_Req(), USER)
    assert any(rule["id"] == created["id"] for rule in svc.list_rules(USER))
    assert not any(rule["id"] == created["id"] for rule in svc.list_rules(ADMIN))
    with pytest.raises(AppError):
        svc.set_rule_active(created["id"], False, ADMIN)


def test_duplicated_rule_participates_in_check(env):
    """「复制」出来的规则（is_default 恒为 false）也必须生效。"""
    db, svc, tmp = env
    _rule(db, name="原文号规则", checks={"font_size_pt": 16}, is_default=True)
    doc = _make_docx(tmp / "o.docx")

    res = _check(svc, doc)

    assert any(i["element"] == "字号" for i in res["issues"])


def test_inactive_rule_is_ignored(env):
    """停用的个人规则不参与校验；其他国标规则继续生效。"""
    db, svc, tmp = env
    db_svc = FormatCheckService(db, _Assistant("[]"), None)
    disabled = _rule(db, name="停用规则", checks={"font_size_pt": 16}, is_active=False)
    doc = _make_docx(tmp / "p.docx")

    res = _check(db_svc, doc, use_ai=True)

    assert res["check_mode"] == "hybrid"
    assert disabled.id not in {r["id"] for r in res["rules_used"]}


def test_create_rule_rejects_empty_checks(env):
    """保存一条没有任何可执行校验项的规则必须 400。

    否则界面提示「规则已保存」，但校验永远查不出问题，用户无法判断是规则没生效
    还是文档本来就合规。
    """
    db, svc, tmp = env

    class _Req:
        target = "body"
        name = "空规则"
        checks = {"invented_key": 1}
        severity = "error"
        is_default = True
        is_active = True
        remark = ""

    with pytest.raises(AppError) as e:
        svc.create_rule(_Req(), ADMIN)
    assert e.value.status_code == 400


# ---------------- 权限 ----------------

def test_record_owner_is_enforced(env):
    """别人的记录不能读；管理员可越权读（后台排障需要）。"""
    db, svc, tmp = env
    _rule(db)
    doc = _make_docx(tmp / "q.docx")
    res = _check(svc, doc, user=ADMIN)

    # 管理员属于 ADMIN_OR_ABOVE，可读他人记录
    assert svc.get_record(res["id"], ADMIN)["id"] == res["id"]

    outsider = User(username="o", email="o@x.local", hashed_password="x",
                    id="u-fc-3")
    _ensure_user(db, outsider)
    with pytest.raises(AppError) as e:
        FormatCheckService(db, None, None).get_record(res["id"], outsider)
    assert e.value.status_code in (403, 404)


# ---------------- HTTP 层冒烟（按钮 → 接口 → 响应契约） ----------------

def test_http_button_flow_smoke(tmp_path):
    """桌面端每个按钮打的是这些接口：路径 / 参数名 / 响应字段必须与设计一致。

    只验契约不验业务（业务由上面的服务层用例覆盖）：路径拼错、DTO 字段名写错、
    鉴权漏配都会在这里暴露。
    """
    from fastapi.testclient import TestClient

    from app.interfaces.deps import get_current_user
    from app.main import app

    db = SessionLocal()
    try:
        _ensure_user(db, ADMIN)
        _rule(db)
        app.dependency_overrides[get_current_user] = lambda: ADMIN
        try:
            with TestClient(app) as c:
                base = "/api/v1/format-check"
                doc = _make_docx(tmp_path / "http.docx")

                r = c.post(f"{base}/check", files={"file": (doc.name, doc.read_bytes())},
                           params={"use_ai": "false"})
                assert r.status_code == 200, r.text
                rid = r.json()["id"]
                assert r.json()["record_id"] == rid

                assert c.get(f"{base}/records/{rid}").status_code == 200
                assert c.get(f"{base}/records/{rid}/paragraphs",
                             params={"version": "current"}).status_code == 200
                assert c.get(f"{base}/rules").status_code == 200

                issue = next(i for i in r.json()["issues"] if i["element"] == "字号")
                r2 = c.post(f"{base}/records/{rid}/apply", json={"issue_id": issue["id"]})
                assert r2.status_code == 200, r2.text
                assert issue["id"] in r2.json()["applied_ids"]

                r3 = c.post(f"{base}/records/{rid}/undo", json={"issue_id": issue["id"]})
                assert r3.status_code == 200 and r3.json()["applied_ids"] == []

                assert c.post(f"{base}/records/{rid}/recheck").status_code == 200

                r4 = c.post(f"{base}/fix", json={"record_id": rid})
                assert r4.status_code == 200, r4.text
                assert r4.content[:2] == b"PK"      # 修正稿是 docx

                r5 = c.post(f"{base}/preview-fix",
                            json={"record_id": rid, "accepted_indices": [issue["id"]]})
                assert r5.status_code == 200 and "paragraphs" in r5.json()

                assert c.put(f"{base}/records/{rid}/content",
                             json={"paragraphs": ["标题", "正文"]}).status_code == 200
                assert c.delete(f"{base}/records/{rid}").status_code == 200
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            db.query(FormatCheckRecordModel).delete()
            db.query(FormatRuleModel).delete()
            db.commit()
    finally:
        db.close()


def test_http_rules_are_personal_and_toggleable(tmp_path):
    """普通用户能管理自己的规则，停用后仍能从列表中找回。"""
    from fastapi.testclient import TestClient

    from app.interfaces.deps import get_current_user
    from app.main import app

    app.dependency_overrides[get_current_user] = lambda: USER
    try:
        with TestClient(app) as c:
            base = "/api/v1/format-check"
            body = {"name": "r", "target": "body", "checks": {"font_size_pt": 16},
                    "severity": "error", "is_default": True, "is_active": True}
            created = c.post(f"{base}/rules", json=body)
            assert created.status_code == 200
            rid = created.json()["id"]
            listed = c.get(f"{base}/rules").json()
            assert any(r["id"] == rid and not r["is_default"] for r in listed)
            assert c.patch(f"{base}/rules/{rid}/active",
                           json={"is_active": False}).status_code == 200
            assert any(r["id"] == rid and not r["is_active"]
                       for r in c.get(f"{base}/rules").json())
            # 白话 → 校验项的 AI 编译不落库，任何登录用户都可用。
            # 400 = 网关/AI 返回内容映射不出校验项（mock 网关下就是这个结果），
            # 502/503 = AI 不可用，三者都不是权限问题；关键是普通用户不被 403 拦。
            assert c.post(f"{base}/rules/compile",
                          json={"target": "body", "description": "正文三号字"}).status_code in (
                200, 400, 502, 503)
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_delete_record_cleans_files(env):
    """删除记录要连带清理原始稿 / 当前稿 / 修正稿。"""
    db, svc, tmp = env
    _rule(db)
    doc = _make_docx(tmp / "r.docx")
    res = _check(svc, doc)
    target = next(i for i in res["issues"] if i["element"] == "字号"
                  and i["paragraph_index"] == 1)
    svc.apply_issue(res["id"], target["id"], ADMIN)
    svc.fix_document(res["id"], None, ADMIN)

    out = svc.delete_record(res["id"], USER if False else ADMIN)

    assert out["id"] == res["id"]
    assert not (svc.check_dir / f"{res['id']}.docx").exists()
    assert not (svc.check_dir / f"{res['id']}_fixed.docx").exists()
    assert not (svc.check_dir / f"{res['id']}_current.docx").exists()
