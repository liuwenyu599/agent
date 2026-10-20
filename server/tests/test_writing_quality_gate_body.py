from app.application.writing.quality_gate import QualityGate


def test_body_only_skips_fields_stored_outside_body():
    body = "一、工作安排\n" + "请各部门按职责推进相关工作，及时报送执行情况。" * 16
    result = QualityGate().evaluate(body, topic="相关工作", body_only=True)
    messages = [issue["message"] for issue in result["issues"]]
    assert not any("缺少" in message for message in messages)
    assert "主题相关性弱" not in messages


def test_short_letter_uses_letter_length_threshold():
    body = "关于经费结算事宜，现将有关事项函告如下。" + "请按约定核对票据、金额和付款进度。" * 12
    result = QualityGate().evaluate(body, body_only=True, document_type="函")
    assert not any("正文偏短" in issue["message"] for issue in result["issues"])


def test_explicit_length_target_flags_large_shortfall_and_overrun():
    gate = QualityGate()
    short = gate.evaluate("一、情况\n" + "工作已经完成。" * 100,
                          body_only=True, word_count_target=3000)
    assert any("正文偏短" in issue["message"] for issue in short["issues"])
    long = gate.evaluate("一、情况\n" + "工作已经完成。" * 300,
                         body_only=True, word_count_target=500)
    assert any("正文偏长" in issue["message"] for issue in long["issues"])


def test_garbled_question_marks_between_chinese_words_block_save():
    result = QualityGate().evaluate("一、情况\n法??副校长参加活动。", body_only=True)
    assert result["level"] == "D"
    assert any("乱码" in issue["message"] for issue in result["issues"])


# 提纲式退化检测误判回归（2026-10-20，生产 WRITING_QUALITY_GATE_D 误拦通知稿）：
# 「（一）段旨句。正文……」连写是通知/方案类公文的标准写法，不能把长行计为标题。
NOTICE_WITH_INLINE_BODY = (
    "社区矫正教育帮扶工作通知\n\n"
    "各司法所：\n\n"
    "为深入贯彻落实《中华人民共和国社区矫正法》及其实施办法，进一步提升我区社区矫正"
    "教育帮扶工作的规范化、专业化水平，有效促进社区矫正对象顺利融入社会，预防和减少"
    "重新违法犯罪，结合我区工作实际，现就做好社区矫正教育帮扶工作有关事项通知如下。\n\n"
    "一、工作目标\n\n"
    "坚持惩罚与教育相结合、管理与帮扶相统一的原则，以提升社区矫正质量为核心，以分级"
    "教育和精准帮扶为抓手，构建全方位、多层次的社区矫正教育帮扶体系。通过强化法治"
    "道德教育、心理疏导干预及社会适应性帮扶，切实增强社区矫正对象的法治观念、社会"
    "责任感和生活信心，降低再犯风险，维护社会和谐稳定。\n\n"
    "二、主要任务\n\n"
    "（一）深化分类分级教育，提升矫正实效。各司法所要根据社区矫正对象的犯罪类型、"
    "心理特点及危险等级，制定个性化的教育矫正方案。常态化开展法治教育和道德教育，"
    "定期组织集中学习、案例警示及公益劳动，确保每月教育学习时间不少于规定学时。\n\n"
    "（二）强化心理疏导干预，关注身心健康。建立健全心理健康筛查与评估机制，对新入矫"
    "对象进行全面的心理测评，对重点对象实行定期跟踪回访。加强与专业心理咨询机构的"
    "合作，引入社会工作者和心理咨询师，为有心理困扰或行为偏差的社区矫正对象提供"
    "一对一的心理辅导和危机干预。\n\n"
    "（三）加大社会帮扶力度，促进顺利回归。积极联合民政、人社、教育等部门及社会组织，"
    "搭建多元化帮扶平台。对有就业意愿的社区矫正对象，提供职业技能培训、岗位推荐及"
    "创业指导等服务，帮助其解决生计难题。\n\n"
    "三、工作要求\n\n"
    "（一）提高政治站位，加强组织领导。各司法所要高度重视社区矫正教育帮扶工作，将其"
    "纳入重要议事日程，明确分管领导和具体责任人，确保各项任务有人抓、有人管、有人落实。\n\n"
    "（二）强化督导考核，确保工作实效。局机关将定期对各司法所教育帮扶工作情况进行"
    "督导检查，对工作不力、落实不到位的，予以通报批评并限期整改。\n\n"
    "（三）及时总结报告，反映工作动态。各司法所要注意收集工作中的好经验、好做法，"
    "每季度末将工作开展情况报送局社区矫正管理局。\n\n"
    "XX区司法局\n"
    "2026年10月20日"
)


def test_inline_heading_with_body_is_not_outline_degeneration():
    result = QualityGate().evaluate(NOTICE_WITH_INLINE_BODY)
    messages = [issue["message"] for issue in result["issues"]]
    assert result["level"] != "D"
    assert not any("提纲式退化" in message for message in messages)


def test_short_inline_items_notice_is_not_outline_degeneration():
    # 条目式连写短通知（会议通知标准形态）：每条 15~25 字、自带实质内容
    body = (
        "关于召开社区矫正业务培训会议的通知\n\n"
        "各司法所：\n\n"
        "经研究，定于2026年10月28日召开全区社区矫正业务培训会议。现将有关事项通知如下：\n\n"
        "一、会议时间：2026年10月28日上午9时至12时。\n"
        "二、会议地点：局机关五楼会议室。\n"
        "三、参会人员：各司法所所长及社区矫正专干。\n"
        "四、会议内容：学习社区矫正法实施办法，交流教育帮扶经验。\n"
        "五、有关要求：请参会人员提前10分钟到场，携带培训手册。\n\n"
        "XX区司法局\n"
        "2026年10月20日"
    )
    result = QualityGate().evaluate(body)
    messages = [issue["message"] for issue in result["issues"]]
    assert not any("提纲式退化" in message for message in messages)


def test_pure_skeleton_without_body_is_still_flagged():
    # 标题+次级标题堆叠、非标题行几乎无实质内容 → 仍须按硬伤拦截
    body = (
        "社区矫正教育帮扶工作通知\n\n"
        "各司法所：\n\n"
        "一、工作目标\n"
        "二、主要任务\n"
        "（一）加强教育\n"
        "（二）强化帮扶\n"
        "（三）促进回归\n"
        "三、工作要求\n"
        "四、保障措施\n\n"
        "XX区司法局"
    )
    result = QualityGate().evaluate(body)
    assert result["level"] == "D"
    assert any("提纲式退化" in issue["message"] for issue in result["issues"])


def test_heading_lines_with_short_body_paragraphs_pass():
    # 段旨句单独成行 + 每节一段短正文：合法公文形态，不得拦截
    body = (
        "社区矫正教育帮扶工作通知\n\n"
        "各司法所：\n\n"
        "为做好相关工作，现将有关事项通知如下。\n\n"
        "一、工作目标\n"
        "围绕社区矫正教育帮扶工作，细化教育、帮扶和衔接措施，提升工作规范性。\n\n"
        "二、主要任务\n"
        "结合实际情况开展分类教育，落实困难帮扶和部门协同，及时记录办理情况。\n\n"
        "三、工作要求\n"
        "压实责任，加强过程管理，发现问题及时整改，确保各项措施有序落实。\n\n"
        "四、保障措施\n"
        "加强组织领导和经费保障，确保各项工作有序推进、取得实效。\n\n"
        "XX区司法局\n"
        "2026年10月20日"
    )
    result = QualityGate().evaluate(body)
    messages = [issue["message"] for issue in result["issues"]]
    assert not any("提纲式退化" in message for message in messages)
