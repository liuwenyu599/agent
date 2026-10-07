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
