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

    @staticmethod
    def _writing_draft() -> str:
        """返回一份确定性的完整测试稿，确保测试覆盖真实质量门而不是绕过质量门。"""
        return (
            "为进一步规范有关工作安排，确保各项任务有序推进，现将有关事项说明如下。"
            "各责任环节应结合实际情况细化工作步骤，明确办理要求和衔接方式，做到任务有人承接、"
            "过程有人跟进、结果能够核验。对已经明确的事项，要按照既定要求组织实施；对需要协同"
            "处理的事项，要提前做好沟通，避免因信息不一致影响整体进度。\n\n"
            "工作推进过程中，要坚持实事求是和规范办理，重要情况及时记录，关键节点及时反馈。"
            "涉及材料汇总、情况报送和内部审核的，应保证口径一致、内容完整、表述准确，不得以概括"
            "说明代替必要的事实说明。对发现的问题，应区分轻重缓急及时处理；暂时不能解决的，要"
            "明确后续安排和责任衔接，防止事项长期搁置。\n\n"
            "要加强过程协调和质量控制。各环节在完成本职任务的同时，应关注前后流程之间的衔接，"
            "对可能影响进度的情况提前研判。需要多方配合的，应明确沟通渠道和反馈方式，减少重复"
            "报送和无效流转。对已经形成的材料，应认真校核文字、数据和逻辑关系，保证内容前后一致，"
            "避免出现遗漏、矛盾或者表述含混等问题。\n\n"
            "同时，要做好资料整理和工作留痕。形成的过程材料应按照统一要求分类保存，便于后续查询、"
            "复核和总结。对重要事项的办理依据、处理过程和最终结果，应保持基本记录完整。涉及后续"
            "持续推进的工作，要在阶段性完成后及时梳理进展，明确下一步任务，使工作安排能够连续衔接。\n\n"
            "请各有关方面根据实际工作需要认真落实上述要求，在执行过程中发现的新情况、新问题，"
            "应及时沟通研究并妥善处理，确保整体工作规范、有序、稳定推进。"
        )

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

        # 写作集成测试应通过一份本身合格的 mock 正文走完整 QualityGate，不能靠测试环境跳过。
        if "这是公文起草任务" in system:
            return self._writing_draft()

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
