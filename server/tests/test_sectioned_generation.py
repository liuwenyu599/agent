from app.application.writing.sectioned_generation_service import SectionedGenerationWritingTaskService


def test_long_report_uses_sectioned_generation_without_explicit_word_target():
    assert SectionedGenerationWritingTaskService._should_section({
        "document_type": "工作总结", "word_count_target": None,
    }) is True
    assert SectionedGenerationWritingTaskService._should_section({
        "document_type": "通知", "word_count_target": None,
    }) is False
    assert SectionedGenerationWritingTaskService._should_section({
        "document_type": "通知", "word_count_target": 2000,
    }) is True
    assert SectionedGenerationWritingTaskService._should_section({
        "document_type": "工作总结", "word_count_target": 3000,
    }, outline_only=True) is False


def test_fallback_plan_is_multi_section_and_budgeted():
    """兜底计划只规定「每节写什么」，不再规定小标题。

    此前 heading 写死「一、基本情况」这类报告骨架，未匹配文种一律落到「报告」，
    导致讲话稿、发言稿等连续行文体例被套上不相称的小标题——这是「讲话稿怎么有
    小标题」的根因。现改为heading 留空，由模型按文种体例自行决定是否设小标题。
    """
    plan = SectionedGenerationWritingTaskService._fallback_plan({
        "document_type": "工作总结", "word_count_target": 2400,
    })
    assert len(plan) == 4
    # heading 统一留空 = 不注入小标题
    assert all(item["heading"] == "" for item in plan)
    # 内容要求（focus）必须保留，否则各节无从区分
    assert all(item["focus"] for item in plan)
    assert all(item["target_chars"] >= 350 for item in plan)
    assert sum(item["target_chars"] for item in plan) == 2400


def test_short_model_plan_cannot_override_requested_length():
    plan = [{"target_chars": 300}] * 4
    assert not SectionedGenerationWritingTaskService._plan_meets_length(plan, 4000)
    assert SectionedGenerationWritingTaskService._plan_meets_length(
        SectionedGenerationWritingTaskService._fallback_plan({
            "document_type": "报告", "word_count_target": 4000,
        }), 4000)
    assert SectionedGenerationWritingTaskService._section_is_short("正文" * 390, 1000)
    assert not SectionedGenerationWritingTaskService._section_is_short("正文" * 410, 1000)


def test_normalize_section_adds_expected_heading_and_stops_next_section_spill():
    raw = "全文标题\n一、基本情况\n第一段。\n第二段。\n二、主要工作\n不应属于本节。"
    result = SectionedGenerationWritingTaskService._normalize_section(raw, "一、基本情况")
    assert result == "一、基本情况\n第一段。\n第二段。"
    assert "二、主要工作" not in result

    missing_heading = SectionedGenerationWritingTaskService._normalize_section(
        "这里是正文第一段。\n这里是正文第二段。", "三、存在问题"
    )
    assert missing_heading.startswith("三、存在问题\n")


def test_section_instruction_reserves_neighbor_content_and_structured_fields():
    ctx = {
        "document_type": "工作总结",
        "topic": "公共法律服务工作",
        "purpose": "年度总结",
        "key_facts": ["开展法律咨询活动", "推进村居法律顾问服务"],
    }
    section = {"heading": "二、主要做法和成效", "focus": "写主要做法", "target_chars": 600}
    text = SectionedGenerationWritingTaskService._section_instruction(
        ctx, section, ["一、基本情况"], ["三、存在问题", "四、下一步工作"]
    )
    assert "只写当前这一节" in text
    assert "前文章节（禁止重复）：一、基本情况" in text
    assert "后续章节（内容留给后文，不要提前展开）：三、存在问题、四、下一步工作" in text
    assert "不得输出全文标题、主送机关、文号" in text
