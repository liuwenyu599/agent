"""公文文种、文号、排版与写作台性能关键路径回归测试。"""

from io import BytesIO

from docx import Document
from docx.shared import Pt

from app.application.chat.docx_export import (
    FONT_BODY,
    FONT_H1,
    FONT_H2,
    FONT_TITLE,
    generate_official_document,
    markdown_to_docx,
    _split_markdown_table_row,
)
from app.application.writing.content_check import ContentChecker
from app.application.writing.postprocessor import (
    TODAY_STR,
    PostProcessor,
    derive_daizi,
)
from app.application.writing.task_service import WritingTaskService
from app.application.writing.task_parser import (
    normalize_recipient_name,
    parse_message,
)


def test_markdown_table_without_trailing_pipe_keeps_last_cell():
    assert _split_markdown_table_row("| 指标 | 数值 |") == ["指标", "数值"]
    assert _split_markdown_table_row("| 指标 | 数值") == ["指标", "数值"]
    assert _split_markdown_table_row("指标 | 数值") == ["指标", "数值"]


def test_rule_of_law_office_uses_correct_document_number_prefix():
    authority = "中共广州市白云区委全面依法治区委员会办公室"
    assert derive_daizi(authority) == "云法治办发"


def test_draft_instruction_keeps_document_type_and_content_boundary():
    svc = WritingTaskService.__new__(WritingTaskService)
    instruction = svc._build_draft_instruction({
        "document_type": "通知",
        "title": "关于报送有关材料的通知",
        "topic": "报送有关材料",
        "recipient": "各镇街、各部门",
        "authority": "中共广州市白云区委全面依法治区委员会办公室",
        "requirements": "只写报告内容、报送要求、工作要求",
    }, outline_only=False)

    assert "文种：通知" in instruction
    assert "不得把通知写成工作要点" in instruction
    assert "不得把通知写成工作要点" in instruction
    assert "把报送事项扩写成全年工作部署" in instruction
    assert "文号与成文日期由系统程序处理" in instruction


def test_postprocessor_injects_real_current_signoff_date():
    text = (
        "关于报送有关材料的通知\n\n"
        "请按要求报送有关材料。\n\n"
        "中共广州市白云区委全面依法治区委员会办公室"
    )
    out, _events, _number, out_date = PostProcessor().process(
        text,
        signoff_hint="中共广州市白云区委全面依法治区委员会办公室",
        inject_docnum=False,
        inject_date=True,
    )
    assert TODAY_STR in out
    assert out_date == TODAY_STR
    assert "2026年X月X日" not in out


class _FakeDb:
    def add(self, _obj):
        pass

    def commit(self):
        pass

    def refresh(self, _obj):
        pass


class _BoomInterpreter:
    def interpret(self, *args, **kwargs):
        raise AssertionError("planned_context 路径不应再次调用 LLM")


def test_planned_context_skips_second_llm_interpretation():
    svc = WritingTaskService(_FakeDb())
    svc.interpreter = _BoomInterpreter()

    result = svc.create_task(
        "u1",
        "请起草一份关于报送材料的通知",
        planned_context={
            "document_type": "通知",
            "title": "关于报送有关材料的通知",
            "topic": "报送有关材料",
            "recipient": "各镇街、各部门",
            "authority": "中共广州市白云区委全面依法治区委员会办公室",
        },
    )

    ctx = result["task_context"]
    assert ctx["document_type"] == "通知"
    assert ctx["title"] == "关于报送有关材料的通知"
    assert ctx["recipient"] == "各镇街、各部门"


def test_docx_export_recognizes_plain_text_official_headings_and_indent():
    buf = markdown_to_docx(
        "一、总体要求\n"
        "这是普通正文第一段，用于检查正文格式。\n"
        "（一）明确工作安排\n"
        "这是普通正文第二段。",
        title="测试通知",
    )
    doc = Document(BytesIO(buf.getvalue()))
    h1 = next(p for p in doc.paragraphs if p.text == "一、总体要求")
    body = next(p for p in doc.paragraphs if p.text == "这是普通正文第一段，用于检查正文格式。")
    h2 = next(p for p in doc.paragraphs if p.text == "（一）明确工作安排")

    assert h1.runs[0].font.name == FONT_H1
    assert h1.runs[0].font.size == Pt(16)
    assert h2.runs[0].font.name == FONT_H2
    assert h2.runs[0].font.size == Pt(16)
    assert body.runs[0].font.name == FONT_BODY
    assert body.runs[0].font.size == Pt(16)
    assert body.paragraph_format.first_line_indent == Pt(32)
    assert body.paragraph_format.line_spacing == Pt(28)


def test_body_structure_strips_duplicate_title_and_recipient():
    ctx = {
        "document_type": "通知",
        "title": "关于报送有关材料的通知",
        "recipient": "各镇街、各部门",
    }
    raw = (
        "关于报送有关材料的通知\n\n"
        "各镇街、各部门：\n\n"
        "现就有关事项通知如下。"
    )
    assert WritingTaskService._strip_leading_structural_fields(raw, ctx) == (
        "现就有关事项通知如下。"
    )


def test_clear_plan_uses_rule_fast_without_llm_or_material_search():
    svc = WritingTaskService.__new__(WritingTaskService)
    svc.db = None
    svc.rag = None
    svc._interpret = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("明确文种+主题不应调用 LLM 规划"))
    svc._plan_materials = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("未要求参考材料时不应同步做材料向量检索"))
    svc._plan_knowledge = lambda *args, **kwargs: []
    svc._plan_template = lambda *args, **kwargs: {}

    result = svc.plan_task("u1", "请起草一份关于社区矫正工作的通知")

    assert result["source"] == "rule_fast"
    assert result["doc_type"] == "通知"
    assert "社区矫正" in result["title"]
    assert result["materials"] == []


def test_official_export_keeps_red_header_separate_from_document_title():
    authority = "中共广州市白云区委全面依法治区委员会办公室"
    title = "关于报送有关材料的通知"
    buf = generate_official_document(
        content="现就有关事项通知如下。",
        title=title,
        doc_number="",
        recipient="各镇街、各部门：",
        signature=authority,
        date_text=TODAY_STR,
    )
    doc = Document(BytesIO(buf.getvalue()))
    texts = [p.text for p in doc.paragraphs if p.text.strip()]

    assert texts[0] == authority + "文件"
    assert title in texts
    assert texts.index(title) > texts.index(authority + "文件")
    assert not any("××司发" in t or "XX" in t or "××" in t for t in texts)
    title_p = next(p for p in doc.paragraphs if p.text == title)
    assert title_p.runs[0].font.name == FONT_TITLE
    assert title_p.runs[0].font.size == Pt(22)
    assert title_p.runs[0].bold is not True
    assert all(not p.text.strip() for s in doc.sections for p in s.header.paragraphs)



def test_postprocessor_corrects_explicit_multiplication_amount():
    raw = "经测算，1336 × 150 × 12 = 239.85 万元。"
    out, events, _number, _date = PostProcessor().process(
        raw, inject_docnum=False, inject_date=False)
    assert "240.48 万元" in out
    assert "239.85 万元" not in out
    assert any("算术校正" in e for e in events)


def test_correspondence_uses_official_ending_and_concise_prompt():
    svc = WritingTaskService.__new__(WritingTaskService)
    instruction = svc._build_draft_instruction({
        "document_type": "函",
        "topic": "经费结算",
        "recipient": "广州市白云区财政局",
        "authority": "广州市白云区司法局",
    }, outline_only=False)
    assert "3-5 个自然段或部分" in instruction
    assert "800-1200 字" in instruction
    assert "6-8 个章节" not in instruction
    assert "不得使用书信式“此致、敬礼”" in instruction

    raw = "有关事项说明如下。\n\n此致\n敬礼"
    out, events, _number, _date = PostProcessor().process(
        raw, inject_docnum=False, inject_date=False, document_type="函")
    assert "此致" not in out
    assert "敬礼" not in out
    assert "特此函告。" in out
    assert any("函件结语校正" in e for e in events)


def test_placeholder_docnum_and_date_are_removed_or_replaced():
    raw = (
        "关于测试事项的函\n"
        "xx司发〔2026〕xx号\n\n"
        "正文。\n\n"
        "广州市白云区司法局\n"
        "2026年×月×日"
    )
    out, events, number, out_date = PostProcessor().process(
        raw,
        signoff_hint="广州市白云区司法局",
        inject_docnum=False,
        inject_date=True,
        document_type="函",
    )
    assert "xx司发" not in out
    assert "×月×日" not in out
    assert TODAY_STR in out
    assert number is None
    assert out_date == TODAY_STR


def test_baiyun_recipient_is_normalized_to_full_agency_name():
    assert normalize_recipient_name("白云区财政局") == "广州市白云区财政局"


def test_multiplication_with_chinese_units_is_corrected():
    """中文量词（人/元/个月）夹在数字与运算符之间时也必须能校正。"""
    raw = "按现有人民调解员1336人计算，预算经费为1336人×150元×12个月=239.85万元。"
    out, events, _number, _date = PostProcessor().process(
        raw, inject_docnum=False, inject_date=False)
    assert "240.48万元" in out
    assert "239.85万元" not in out
    assert any("算术校正" in e for e in events)


def test_small_bracket_docnum_is_normalized_to_standard_bracket():
    """LLM 常用 ﹝﹞ 全角小括号，国标应为〔〕。"""
    raw = "根据《广州市关于加强人民调解工作的意见》（穗司发﹝2018﹞278号）执行。"
    out, events, _number, _date = PostProcessor().process(
        raw, inject_docnum=False, inject_date=False)
    assert "穗司发〔2018〕278号" in out
    assert "﹝2018﹞" not in out
    assert any("历史文号格式规范化" in e for e in events)


def test_word_count_target_does_not_cancel_letter_structure_rule():
    """指定字数不能把「函件 3-5 段 / 条目不超 5 个」的结构约束换掉，
    否则模型只能靠加章节凑字数，函会被写成报告。"""
    svc = WritingTaskService.__new__(WritingTaskService)
    instruction = svc._build_draft_instruction({
        "document_type": "函",
        "topic": "划拨人民调解员工作补贴",
        "recipient": "广州市白云区财政局",
        "word_count_target": 1500,
    }, outline_only=False)
    assert "1500 字" in instruction
    assert "一级条目不得超过 5 个" in instruction
    assert "严禁靠增加章节条目凑字数" in instruction


def test_letter_ending_is_fixed_even_without_document_type():
    """对话写作入口不传 document_type 时，也要能识别函并校正结语。"""
    raw = (
        "现将划拨2027年村（社区）兼职人民调解员工作补贴的相关事宜函告如下：\n"
        "一、补贴发放依据\n依据相关文件执行。\n\n"
        "此致\n敬礼！\n"
        "广州市白云区司法局\n"
        "2026年X月X日"
    )
    out, events, _number, _date = PostProcessor().process(
        raw, signoff_hint="广州市白云区司法局",
        inject_docnum=False, inject_date=True, document_type=None)
    assert "敬礼" not in out
    assert "特此函告。" in out
    assert "X月X日" not in out
    assert any("函件结语校正" in e for e in events)
    assert normalize_recipient_name("广州市白云区财政局") == "广州市白云区财政局"
    assert normalize_recipient_name("各镇街、各部门") == "各镇街、各部门"


def test_document_number_citation_without_retrieved_evidence_is_flagged():
    result = ContentChecker().check(
        "根据穗司发〔2018〕278号有关要求执行。",
        sources=[{"content": "这里只包含其他政策材料。"}],
    )
    messages = [i["message"] for i in result["issues"]]
    assert any("穗司发〔2018〕278号" in m and "未在本次检索材料中找到" in m
               for m in messages)


def test_unsupported_document_number_is_removed_before_delivery():
    text = "根据穗司发〔2018〕278号有关要求，现提出如下安排。"
    cleaned, warnings = WritingTaskService._guard_external_document_numbers(
        text,
        sources=[{"content": "这里只包含其他政策材料。", "source": "其他材料（第1段）"}],
        ctx={},
    )
    assert "穗司发〔2018〕278号" not in cleaned
    assert "相关文件" in cleaned
    assert warnings == ["穗司发〔2018〕278号"]


def test_document_number_with_retrieved_evidence_is_preserved():
    text = "根据穗司发〔2018〕278号有关要求，现提出如下安排。"
    cleaned, warnings = WritingTaskService._guard_external_document_numbers(
        text,
        sources=[{
            "content": "依据穗司发〔2018〕278号文件要求执行。",
            "source": "政策依据（第2段）",
        }],
        ctx={},
    )
    assert cleaned == text
    assert warnings == []


class _StubDB:
    def flush(self):
        pass

    def commit(self):
        pass


class _StubTask:
    """最小可用的写作任务替身，只覆盖 revise 真正用到的字段。"""

    def __init__(self, content, ctx):
        self.id = "t-test"
        self.session_id = "s-test"
        self.document_id = "d-test"
        self.context = ctx
        self.current_content = content
        self.version_no = 1
        self.status = "editing"
        self.ai_draft = content
        self.created_at = None
        self.updated_at = None


def test_revise_applies_user_date_before_postprocess():
    """回归：对话里改落款日期，必须真的落到正文上。

    历史 bug：revise() 先 _postprocess 再 merge_context，后处理拿到的还是旧日期；
    紧接着的 `ctx["document_date"] = doc_date` 又把用户刚给的新日期覆盖回去。
    表现为「助手回复说已把落款日期更新为 X，正文里的日期却纹丝不动」。
    """
    svc = WritingTaskService.__new__(WritingTaskService)
    svc.db = _StubDB()

    old = ("关于举办专题讲座的函\n\n"
           "为提升业务能力，拟举办专题讲座。\n\n"
           "广州市白云区司法局\n2026年1月1日")
    ctx = {
        "document_type": "函",
        "title": "关于举办专题讲座的函",
        "authority": "广州市白云区司法局",
        "document_date": "2026年1月1日",
        "document_number_enabled": False,
        "document_number": None,
        "key_facts": [],
    }
    task = _StubTask(old, ctx)

    svc._get_owned = lambda task_id, user_id: task
    svc._load_template = lambda template_id: None
    svc._retrieve = lambda ctx_, user_id, extra_query="": []
    svc._attachment_context = lambda t, ctx_: None
    svc._llm_revise = lambda prompt, sources, attachment_ctx, user_id: old.replace(
        "拟举办专题讲座。", "拟于十月举办专题讲座。")
    svc._snapshot = lambda t, user_id, note=None: ("d-test", 2)

    out = svc.revise("t-test", "u1", "落款日期改成2026年10月10日")

    assert task.context["document_date"] == "2026年10月10日"
    assert "2026年10月10日" in task.current_content
    assert "2026年1月1日" not in task.current_content
    assert out["content_changed"] is True


def test_parser_understands_everyday_phrasings_for_context_updates():
    """回归：用户口语化的改要素说法必须能被解析，否则「我让改的都没改」。

    历史 bug：正则只认「落款是/发文机关是/单位是」这类"是"字结构和
    「日期是/日期为/日期：」，用户说「落款改成 X」「日期再填 X」「落款是今天」
    时 parse_message 返回空（或把年份误判成 time_range），
    于是助手回复"已更新"，实际一个字段都没动。
    """
    from datetime import date

    # 日期：动词覆盖「填/再填/改成/改为/换成/设为」
    assert parse_message("日期再填2026年10月10日") == {"document_date": "2026年10月10日"}
    assert parse_message("落款日期改成2026年10月10日") == {"document_date": "2026年10月10日"}
    assert parse_message("成文日期设为2026年10月10日") == {"document_date": "2026年10月10日"}

    # 「日期再填X」里的年份不能再被当成时间范围
    assert "time_range" not in parse_message("日期再填2026年10月10日")

    # 今天：口语说法
    today = date.today()
    expected_today = f"{today.year}年{today.month}月{today.day}日"
    assert parse_message("落款是今天") == {"document_date": expected_today}
    assert parse_message("日期用今天") == {"document_date": expected_today}

    # 发文机关：动词覆盖「改成/改为/换成/填」
    assert parse_message("落款改成广州市白云区司法局").get("authority") == "广州市白云区司法局"
    assert parse_message("落款是广州市白云区司法局").get("authority") == "广州市白云区司法局"

    # 标题是结构化字段，必须写进 ctx 才会变
    assert parse_message("标题改成关于邀请张教授作专题讲座的函").get("title") == \
        "关于邀请张教授作专题讲座的函"

    # 「标题换一个」没给具体内容，不能瞎猜成标题
    assert "title" not in parse_message("标题换一个")


def test_sync_structured_fields_rewrites_signoff_date_in_body():
    """回归：只改 ctx（不走 AI 改写）时，落款日期必须同步进正文。"""
    svc = WritingTaskService.__new__(WritingTaskService)
    svc.db = _StubDB()

    body = "请予支持为盼。\n\n广州市白云区司法局\n2026年1月1日"
    ctx = {
        "document_type": "函",
        "authority": "广州市白云区司法局",
        "document_date": "2026年10月10日",
        "document_number_enabled": False,
        "document_number": None,
    }
    task = _StubTask(body, ctx)
    svc._snapshot = lambda t, user_id, note=None: ("d-test", 2)

    note = svc._sync_structured_fields(task, "u1")

    assert note
    assert "2026年1月1日" not in task.current_content
    assert "2026年10月10日" in task.current_content
    assert task.version_no == 2


def test_sync_structured_fields_is_noop_when_nothing_to_change():
    svc = WritingTaskService.__new__(WritingTaskService)
    svc.db = _StubDB()

    body = "请予支持为盼。\n\n广州市白云区司法局\n2026年10月10日"
    ctx = {
        "document_type": "函",
        "authority": "广州市白云区司法局",
        "document_date": "2026年10月10日",
        "document_number_enabled": False,
        "document_number": None,
    }
    task = _StubTask(body, ctx)
    svc._snapshot = lambda t, user_id, note=None: ("d-test", 2)

    assert svc._sync_structured_fields(task, "u1") == ""
    assert task.current_content == body
    assert task.version_no == 1
