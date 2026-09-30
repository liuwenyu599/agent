"""Mock 模型适配器：测试/演示用，不联网，确定性输出。"""
import json
import re
from typing import Dict, List


class MockLLMGateway:
    def __init__(self) -> None:
        self.call_count = 0
        self.last_messages: List[Dict[str, str]] = []

    @property
    def model_name(self) -> str:
        return "mock-model"

    @staticmethod
    def _writing_intent(messages: List[Dict[str, str]], last_user: str) -> str:
        """测试环境实现 writing_intent_v2 协议。

        这里只是 Mock 适配器，不参与生产语义路由；目的在于让集成测试模拟
        “真实模型返回结构化意图”，避免生产服务为了测试重新退回 regex fallback。
        """
        try:
            payload = json.loads(last_user)
            msg = str(payload.get("用户最新消息") or "")
            has_draft = bool(payload.get("是否已有正文草稿"))
        except Exception:
            msg = last_user
            has_draft = False

        out = {
            "_schema": "writing_intent_v2",
            "side_effect": "workspace",
            "intent": "update_context",
            "document_type": None,
            "title": None,
            "topic": None,
            "purpose": None,
            "time_range": None,
            "recipient": None,
            "authority": None,
            "key_facts": [],
            "requirements": None,
            "tone": None,
            "word_count_target": None,
            "document_number_enabled": None,
            "document_number": None,
            "document_date": None,
            "revision_instruction": None,
            "revision_mode": None,
            "needs_clarification": False,
            "clarification_question": None,
            "reply": "好的。",
        }

        # 测试夹具中的常见新建任务。这里只模拟模型结果，不作为生产 parser。
        if "工作总结" in msg:
            out["document_type"] = "工作总结"
            if "司法行政" in msg:
                out["topic"] = "司法行政"
            m = re.search(r"(20\d{2})年度", msg)
            if m:
                out["time_range"] = m.group(0)
        elif "通知" in msg:
            out["document_type"] = "通知"
            m = re.search(r"关于([^，。,.]+)", msg)
            if m:
                out["topic"] = m.group(1).strip()
        elif "报告" in msg:
            out["document_type"] = "报告"
            m = re.search(r"写(?:一个|一份)?(.+?)报告", msg)
            if m:
                topic = m.group(1).strip()
                if topic:
                    out["topic"] = topic

        m = re.search(r"主送\s*[：:]\s*([^，。\n]+)", msg)
        if m:
            out["recipient"] = m.group(1).strip()

        m = re.search(r"(?:落款|成文)?(?:日期|时间)?\s*(?:是|改成|改为|：|:)?\s*(20\d{2}年\d{1,2}月\d{1,2}日)", msg)
        if m:
            out["document_date"] = m.group(1)

        if "不要文号" in msg:
            out["document_number_enabled"] = False
        m = re.search(r"([\u4e00-\u9fa5A-Za-z]{1,12}〔20\d{2}〕\d+号)", msg)
        if m:
            out["document_number_enabled"] = True
            out["document_number"] = m.group(1)

        if has_draft and any(k in msg for k in ("润色", "精简", "扩写", "重写", "修改")):
            out["intent"] = "revise_content"
            out["revision_instruction"] = msg
            out["revision_mode"] = "polish" if "润色" in msg else "revise"
        return json.dumps(out, ensure_ascii=False)

    def complete(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        self.call_count += 1
        self.last_messages = messages
        last_user = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "user"), ""
        )
        system = next((m.get("content", "") for m in messages if m.get("role") == "system"), "")

        if "writing_intent_v2" in system:
            return self._writing_intent(messages, last_user)

        # 提示词要求 JSON 输出时返回可解析的最小结果，保证下游解析逻辑可测试
        if "JSON" in last_user or "json" in last_user:
            if "slides" in last_user and re.search(r"\[\{", last_user):
                return json.dumps({
                    "title": "（Mock）司法行政工作汇报",
                    "subtitle": "（Mock）副标题",
                    "slides": [
                        {"type": "cover", "title": "司法行政工作汇报", "subtitle": "阶段总结"},
                        {"type": "content", "title": "主要工作", "points": ["完成法治宣传20场", "调解纠纷120件"]},
                        {"type": "closing", "title": "谢谢聆听，请批评指正"},
                    ]
                }, ensure_ascii=False)
            if re.search(r"JSON\s*数组|\[\{", last_user):
                return "[]"
            return json.dumps(
                {"meeting_name": "（Mock）提取的会议名称", "meeting_time": "下周三上午"},
                ensure_ascii=False,
            )
        return f"（Mock 模型回复）已收到您的请求：{last_user[:200]}"
