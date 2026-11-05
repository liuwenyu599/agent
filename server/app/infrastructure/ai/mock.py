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

        if "工作总结" in msg:
            out["document_type"] = "工作总结"
            if "司法行政" in msg:
                out["topic"] = "司法行政"
            m = re.search(r"(20\d{2})年度", msg)
            if m:
                out["time_range"] = m.group(0)
        elif "致辞" in msg or "讲话" in msg or "发言" in msg:
            out["document_type"] = "致辞稿" if "致辞" in msg else "讲话稿"
            m = re.search(r"(?:写|起草)(?:一份|一篇|一个|个|篇)?(.+?)(?:致辞稿?|讲话稿?|发言稿?)", msg)
            if m:
                out["topic"] = m.group(1).strip()
        elif "新闻稿" in msg:
            out["document_type"] = "新闻稿"
            m = re.search(r"(?:写|起草)(?:一份|一篇|一个|个|篇)?(.+?)新闻稿", msg)
            if m:
                out["topic"] = m.group(1).strip()
        elif "倡议书" in msg:
            out["document_type"] = "倡议书"
            m = re.search(r"(?:写|起草)(?:一份|一篇|一个|个|篇)?(.+?)倡议书", msg)
            if m:
                out["topic"] = m.group(1).strip()
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
    def _writing_draft(last_user: str = "") -> str:
        """返回确定性的合格测试稿；分章节任务按章节生成不同正文，避免伪重复。"""
        section_match = re.search(r"当前章节标题：([^\n]+)", last_user or "")
        heading = section_match.group(1).strip() if section_match else ""
        focus_match = re.search(r"本节职责：([^\n]+)", last_user or "")
        focus = focus_match.group(1).strip() if focus_match else ""
        if heading or focus:
            section_kind = heading or focus
            if any(kind in last_user for kind in ("全文文种：致辞", "全文文种：讲话", "全文文种：发言",
                                                  "全文文种：主持词")):
                if "宣布会议开始" in focus or "开场" in focus:
                    body = "各位领导、各位来宾，大家好！今天我们相聚在这里，共同关注法治建设这件与每个人息息相关的事。首先，我谨向参加活动的同志和朋友们表示欢迎，向长期关心支持这项工作的各界人士表示感谢。能在这样的场合与大家交流，我感到十分高兴。"
                elif "议程" in focus or "串联" in focus:
                    body = "按照今天的议程安排，会议将围绕法治建设各项工作依次进行。刚才，几位同志分别就各自负责的环节作了说明，讲得都很到位。下面我把各环节的安排再作简要提示，也请各位领导和来宾给予指导。"
                elif "贯彻" in focus:
                    body = "会议明确了下一阶段的工作要求，与会同志要抓好传达贯彻，把会议确定的任务落实到具体岗位和具体环节。同时加强跟踪问效，定期梳理进展、查找不足，形成闭环，确保各项要求落到实处。"
                elif "背景" in focus:
                    body = "法治建设离不开群众参与，也离不开日常服务中的耐心沟通。一次咨询、一场宣传、一个纠纷的妥善化解，都能让法律离群众更近一些。今天的活动把大家聚在一起，正是希望把抽象的法治理念转化为看得见、用得上的实际帮助。"
                elif "愿景" in focus or "倡议" in focus:
                    body = "我想借这个机会与大家分享一个朴素的期待：让遇到问题的人知道去哪里寻求帮助，让需要服务的人能够获得清楚、可靠的指引。只要我们多听一听群众的真实需要，把普法讲得更明白，把服务做得更细致，法治就会融入更多人的日常生活。"
                else:
                    body = "最后，再次感谢大家的到来和付出。希望我们以今天的交流为新的起点，继续携手把法治宣传和公共法律服务做得更贴近实际、更贴近群众。祝本次活动圆满成功，祝各位工作顺利、身体健康。谢谢大家！"
            elif "工作开展情况" in section_kind or "基本情况" in section_kind or "推进过程" in section_kind:
                body = (
                    "围绕年度司法行政重点任务，相关工作按照既定部署有序推进。各业务环节结合职责分工，"
                    "持续完善内部衔接和事项办理机制，对阶段任务实行清单化管理，及时掌握进度并协调处理执行中的具体问题。"
                    "在材料流转、情况汇总和事项反馈过程中，注重统一工作口径，保证基础信息能够及时归集并形成连续记录。\n\n"
                    "日常推进中，坚持把规范办理和过程管理结合起来，对需要多方协同的事项明确沟通渠道和反馈节点，"
                    "对已经完成的事项及时整理结果，对仍需持续推进的事项明确后续安排。通过持续梳理流程和加强工作衔接，"
                    "各项任务保持了较为稳定的推进节奏，为后续总结完善和改进工作提供了基础。"
                )
            elif any(word in section_kind for word in ("做法", "成效", "主要工作情况", "主要任务", "重点工作")):
                body = (
                    "一是强化统筹协调。对重点事项实行分类管理，根据任务性质明确责任环节、办理顺序和反馈要求，"
                    "减少重复流转和信息断点。二是加强质量控制，对形成的材料和办理结果进行必要复核，重点检查事实表述、"
                    "逻辑关系和前后口径，发现问题及时纠正。三是完善协同机制，对跨环节事项提前沟通，明确承接关系，"
                    "避免因职责边界不清影响办理进度。\n\n"
                    "通过上述措施，工作过程更加规范，事项衔接更加顺畅，材料整理和内部反馈的及时性得到改善。"
                    "对重要节点形成基本工作记录，也便于后续查询、复盘和持续优化。相关成效仅作流程性概括，"
                    "不虚构具体统计数字、排名或者未经材料证明的外部事实。"
                )
            elif any(word in section_kind for word in ("存在问题", "短板", "制约因素")):
                body = (
                    "从现阶段运行情况看，仍有需要进一步改进的环节。部分事项在跨环节衔接时，信息传递的完整性和及时性仍不稳定，"
                    "个别材料在形成过程中存在口径需要再次核对的情况。对持续时间较长的任务，阶段进展记录还可以进一步细化，"
                    "以便后续人员能够准确掌握前期处理过程。\n\n"
                    "上述问题主要体现为流程协同和过程管理仍需加强，而不是对具体业务成效作无依据判断。后续需要通过明确责任节点、"
                    "优化反馈机制和加强过程复核逐步解决，并结合实际执行情况持续调整，避免简单依靠增加报表或重复报送方式处理。"
                )
            elif any(word in section_kind for word in ("下一步", "后续举措", "保障措施", "实施步骤")):
                body = (
                    "下一阶段将继续围绕规范、高效、可追溯的要求推进工作。首先，进一步细化重点事项清单和责任节点，"
                    "明确不同环节的承接方式和反馈时限；其次，加强对过程材料的整理和复核，对重要事项形成连续记录，"
                    "确保前后信息能够衔接；再次，完善跨环节沟通机制，对可能影响整体进度的问题提前研判并及时协调。\n\n"
                    "同时，根据实际执行情况定期梳理流程中存在的堵点，对能够通过内部优化解决的问题及时调整处理方式。"
                    "对需要长期推进的事项实行阶段性回顾，明确下一阶段任务和责任安排，使工作改进形成闭环，"
                    "在不增加无效负担的前提下提升整体办理质量和协同效率。"
                )
            elif "工作目标、原则" in focus:
                body = (
                    "本项工作以让法治宣传更加贴近社区实际为目标，先摸清服务对象的常见问题，"
                    "再确定适合的宣传内容和参与方式。推进中坚持依法准确、通俗易懂和便于群众参与，"
                    "对未核实的信息不作确定性表述，也不以活动数量代替实际服务效果。\n\n"
                    "整体安排应把前期准备、现场实施和后续反馈衔接起来。准备阶段确认主题、对象和可用材料；"
                    "实施阶段关注群众是否听懂并能找到具体求助渠道；结束后整理意见，作为调整下一次活动的依据。"
                )
            elif "核心任务和具体举措" in focus:
                body = (
                    "围绕群众日常可能遇到的法律问题，先整理权威、适用的基础资料，并将专业表述改写为"
                    "便于理解的问答和案例说明。对涉及个案的内容，应去除个人信息，避免把未核实情节当成事实传播。\n\n"
                    "活动组织可结合咨询、讲解和互动交流安排不同环节。工作人员负责解释适用范围和办理路径，"
                    "对现场不能确定的问题记录后转交相应业务环节核实，再通过约定渠道反馈，不作超出依据的承诺。"
                )
            elif "阶段安排、时间逻辑" in focus:
                body = (
                    "推进顺序分为准备、实施和复盘三个阶段。准备阶段明确活动目标与服务对象，核对拟使用的"
                    "法律资料，确定场地和人员分工；完成必要检查后再进入现场实施，避免材料、设备和人员安排脱节。\n\n"
                    "实施时按介绍主题、讲解重点、接受咨询的顺序开展，并记录需要后续答复的事项。活动结束后"
                    "及时整理反馈和遗留问题，核对办理责任与回复方式，为下一阶段改进提供具体依据。"
                )
            elif "责任、协同、督导" in focus:
                body = (
                    "承办环节负责准备材料和组织现场工作，相关业务人员负责核对专业内容，对需要多方配合的"
                    "事项提前明确联系渠道。负责人在关键节点检查材料准确性、活动安排和问题转办情况，"
                    "发现信息不一致时先核实再发布。\n\n"
                    "对现场秩序、个人信息保护和错误信息传播等风险，应事先准备处置办法。后续督导重点查看"
                    "咨询事项是否得到答复、群众意见是否被记录、需要改进的问题是否有人跟进，避免只有活动记录而没有服务闭环。"
                )
            else:
                body = (
                    "本节围绕既定任务要求展开，重点说明相关工作的推进方式、责任衔接和过程控制。各环节按照职责做好事项承接，"
                    "对需要协同处理的内容及时沟通，对形成的材料做好必要核对，确保工作过程连续、信息口径一致。\n\n"
                    "在执行过程中，对重要节点保留基本记录，并根据实际情况及时调整后续安排。对材料没有提供的具体数字、日期和外部事实，"
                    "不作推断或补写，以保证本节内容保持可核验和可执行。"
                )
            return f"{heading}\n{body}" if heading else body

        if any(kind in last_user for kind in ("文种：致辞", "文种：讲话", "文种：发言")):
            return (
                "各位领导、各位来宾，大家好！今天我们相聚在这里，共同参加这场活动。"
                "首先，我谨向到场的朋友们表示欢迎，向一直关心和支持这项工作的同志们表示感谢。\n\n"
                "此次活动为我们提供了面对面交流的机会。法治建设要真正走进群众生活，"
                "需要把专业知识讲得更清楚，把服务送到有需要的人身边，也需要认真听取大家的意见。"
                "我们期待今天的交流能让更多人了解法律、善用法律，在遇到问题时知道如何寻求帮助。\n\n"
                "我也希望大家把今天的收获带回日常工作和生活中，继续关心和支持法治建设。"
                "让我们从一次具体的沟通、一次务实的服务做起，共同营造尊法学法守法用法的良好氛围。\n\n"
                "最后，再次感谢各位的到来。祝本次活动圆满成功，祝大家工作顺利、身体健康。谢谢大家！"
            )
        if "文种：新闻稿" in last_user:
            return (
                "一场围绕法治宣传的发布活动近日举行。活动聚焦群众关心的法律服务问题，"
                "介绍了面向公众的服务内容和参与方式。现场通过交流与展示，帮助参与者了解"
                "在遇到法律问题时可以获取哪些支持。\n\n"
                "活动主办方表示，后续将结合现场反馈完善信息说明和服务指引，让相关内容"
                "更容易被公众理解和使用。具体活动时间、人数及成果以正式材料为准。"
            )
        if "文种：倡议书" in last_user:
            return (
                "广大市民朋友们：法治与每个人的生活息息相关。遇到问题时，我们可以先了解"
                "适用规则，理性表达诉求，主动寻求依法解决问题的途径。\n\n"
                "让我们从日常小事做起，尊重规则、关心他人，积极参与身边的法治宣传活动。"
                "把学到的法律知识分享给家人和朋友，共同营造守法、用法的良好氛围。"
            )
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

        if "这是写作任务" in system or "这是公文起草任务" in system:
            return self._writing_draft(last_user)

        if "JSON" in last_user or "json" in last_user:
            if "slides" in last_user and re.search(r"\[\{", last_user):
                return json.dumps({
                    "title": "（Mock）司法行政工作汇报",
                    "subtitle": "（Mock）副标题",
                    "style": "工作汇报",
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
