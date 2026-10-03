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
    plan = SectionedGenerationWritingTaskService._fallback_plan({
        "document_type": "工作总结", "word_count_target": 2400,
    })
    assert len(plan) == 4
    assert plan[0]["heading"].startswith("一、")
    assert plan[-1]["heading"].startswith("四、")
    assert all(item["target_chars"] >= 350 for item in plan)
    assert sum(item["target_chars"] for item in plan) == 2400


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
