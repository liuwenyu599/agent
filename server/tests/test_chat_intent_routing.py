from app.application.chat.intent_service import IntentService


def test_polite_read_only_question_is_not_a_writing_request():
    assert not IntentService.is_writing_request("帮我看看这份材料有哪些问题？")
    assert not IntentService.is_writing_request("帮我看看这篇材料如何修改？")
    assert not IntentService.is_writing_request("帮我指出这份通知有哪些问题？")


def test_colloquial_revision_still_routes_to_writing():
    assert IntentService.is_writing_request("这篇太啰嗦了，短一点")
    assert IntentService.is_writing_request("麻烦把第二段写得顺一点")
    assert IntentService.is_writing_request("能不能帮我改成2000字？")
    assert IntentService.is_writing_request("请帮我拟一份通知好吗？")
