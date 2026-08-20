import os
import json
import requests
from typing import List, Dict, Optional
from jinja2 import Template

from backend.config.settings import VLLM_URL, LLM_MODEL, LLM_MAX_MODEL_LEN

class LLMService:
    def __init__(self):
        self.api_url = VLLM_URL
        self.model = LLM_MODEL

        self.prompts = self._load_prompts()

    def _load_prompts(self) -> Dict:
        """加载所有 prompt 模板"""
        prompts = {}
        prompt_dir = os.path.join(os.path.dirname(__file__), "..", "prompts")

        for category in ["write", "search", "rewrite", "summary", "planner"]:
            category_dir = os.path.join(prompt_dir, category)
            if os.path.exists(category_dir):
                for file in os.listdir(category_dir):
                    if file.endswith(".jinja2"):
                        name = file.replace(".jinja2", "")
                        with open(os.path.join(category_dir, file), "r", encoding="utf-8") as f:
                            prompts[f"{category}/{name}"] = f.read()

        return prompts

    def _render_prompt(self, template_name: str, **kwargs) -> str:
        """渲染 prompt 模板"""
        template_str = self.prompts.get(template_name, "")
        if not template_str:
            return self._default_prompt(**kwargs)

        template = Template(template_str)
        return template.render(**kwargs)

    def _default_prompt(self, query: str = None, sources: List[Dict] = None,
                        memories: List[Dict] = None, **kwargs) -> str:
        """精简版 system prompt，去掉自相矛盾的规则"""
        parts = [
            "你是司法局智能助手，擅长公文写作与法律法规问答。请优先结合对话历史理解用户意图，回答准确、简洁、有条理。",
            "重要规则：不得虚构真实单位、人名、时间、地点、政策依据和数据；"
            "用户提供的信息不足时，只询问对结果影响最大的 2~3 个关键问题，"
            "信息足够时直接生成，不要反复提问。",
        ]

        if sources:
            docs = "\n\n".join(f"[参考资料{i+1}]\n{s['content'][:1200]}" for i, s in enumerate(sources))
            parts.append(
                "以下是检索到的参考资料，若与问题相关请据此作答；若不相关请忽略，直接用你自己的知识回答：\n" + docs
            )

        return "\n\n".join(parts)

    def _build_writing_prompt(self, topic: str, examples: list) -> str:
        base_rules = (
            "硬性要求：\n"
            "1. 必须生成完整成文，禁止只列提纲、条目或要点清单；每个部分都要展开为"
            "连贯、完整的正式段落，有具体内容、有事实支撑、有过渡衔接；\n"
            "2. 篇幅要足：总结汇报类一般不少于 1500 字，每个主要部分（如工作完成情况、"
            "存在问题、下一步计划）至少写 2~3 个完整自然段；\n"
            "3. 严格遵循 GB/T 9704-2012《党政机关公文格式》：标题独占一行居中、不换行不断行；"
            "正文分“一、”“（一）”“1.”“（1）”层级；落款含发文机关署名和成文日期；\n"
            "4. 禁止使用 markdown 符号（如 **、##、- 列表符），用纯文本公文排版；\n"
            "5. 禁止出现“当然”“好的”“以下是”“根据您的要求”等对话口吻，"
            "不要输出任何解释性文字，直接给成文正文；\n"
            "6. 不得虚构真实单位、领导姓名、具体时间地点、政策文号和数据；"
            "用户或知识库资料中没有的数据，用××占位或定性描述，不要编造数字；"
            "7. 请示与报告是两种不同文种，严格分开：是请示就只写请示（一文一事，结尾"
            "'妥否，请批示'），是报告就只写报告（只汇报不请求，结尾'特此报告'），"
            "任何情况下标题和文种都不得写成'请示报告'。"
        )
        doc_type = self._detect_doc_type(topic or "")
        if doc_type == "request":
            base_rules += (
                "\n\n【本文是请示，专用要求】一文一事；先讲理由和依据，再提请求事项；"
                "请求事项具体、可批复；结尾只写'妥否，请批示'（或'以上请示，请批复'）；"
                "不得写'特此报告'，不得汇报与请求无关的工作。"
            )
        elif doc_type == "report":
            base_rules += (
                "\n\n【本文是报告，专用要求】只汇报工作、反映情况、回复询问；"
                "全文不得出现请求批准、请求解决、请予拨付等请示性表述；"
                "结尾只写'特此报告'，不得写'妥否，请批示'。"
            )
        elif doc_type == "publicity":
            base_rules = (
                "硬性要求：\n"
                "1. 必须生成完整成稿，禁止只列提纲；\n"
                "2. 这是公众号外宣推文：标题要鲜活吸睛，可用疑问式、感叹式或引号提炼式"
                "（如'“四阶”赋能''“三步”矫正工作法'），标题即看点；\n"
                "3. 正文用具体事例、纠纷或现场开头讲故事，再带出做法与成效，"
                "不要公文式导语，不用'一、（一）、1.'式分条；\n"
                "4. 做法能提炼就提炼为'三步''三心''三链'式工作法并加引号；\n"
                "5. 语言鲜活有温度、段落短小；\n"
                "6. 不出现主送机关、发文机关署名和成文日期；\n"
                "7. 不得虚构单位、人名、时间地点和数据，用户没提供的用定性表述。"
            )
        if not examples:
            return (
                "你是司法局公文写作专家，请按规范的党政机关公文格式撰写，结构完整、行文严谨、内容详实。\n\n"
                + base_rules
            )

        refs = "\n\n".join(
            f"【范文{i+1}：{e['title']}】\n{e['content']}" for i, e in enumerate(examples)
        )
        return f"""你是司法局公文写作专家。请**严格模仿本单位范文**的风格来写作。

        模仿要求：
        1. 结构层次与范文一致（标题、主送机关、正文分条、落款、成文日期）；
        2. 沿用范文的称谓、固定套语、过渡句和用词习惯；
        3. 保持相同的行文口吻、正式程度和详实程度；
        4. 只替换成与本次主题相关的内容，范文里具体的单位名、人名、数字、日期不要照搬。

        {refs}

        {base_rules}"""

    def _build_reference_template_context(self, reference_template: Dict) -> str:
        """把"参考模板"构建为写作参考约束（不是填空表单）。

        reference_template 字段来自 WritingTemplate：
        name / content_template / system_prompt / writing_style / word_count /
        need_red_header / need_signature / need_date / need_doc_number / keywords
        """
        t = reference_template
        format_reqs = [f"字数约 {t.get('word_count', 1000)} 字"]
        format_reqs.append("需要落款单位" if t.get("need_signature", True) else "无需落款")
        format_reqs.append("需要成文日期" if t.get("need_date", True) else "无需成文日期")
        if t.get("need_doc_number"):
            format_reqs.append("需要发文字号（用户未提供时用××占位）")
        if t.get("need_red_header"):
            format_reqs.append("属红头文件，行文按正式发文规范")

        parts = [
            f"【参考模板：{t.get('name')}】",
            "用户选择了该参考模板。它是写作结构与风格的参考约束，不是填空表单；"
            "用户未提供的具体事实不要虚构。",
        ]
        if t.get("system_prompt"):
            parts.append(f"写作指导：{t['system_prompt']}")
        if t.get("content_template"):
            parts.append(f"结构要求：{t['content_template']}")
        if t.get("category") == "宣传材料" or t.get("writing_style") in ("公众号推文", "媒体通讯"):
            parts.append("重要：以上结构只是参考范式，请根据本次任务内容灵活组织文章结构"
                         "（活动报道、机制宣传、案例宣传的结构各不相同），不要生搬硬套固定框架。")
        parts.append("格式要求：" + "；".join(format_reqs) + "。")
        if t.get("keywords"):
            parts.append(f"补充要求：{t['keywords']}")
        return "\n".join(parts)

    def _call_vllm(self, messages: List[Dict], temperature: float = 0.7, max_tokens: int = 4096) -> str:
        """调用 vLLM 服务（OpenAI 兼容 API）

        上下文预算以 settings.LLM_MAX_MODEL_LEN（vLLM 启动参数 max_model_len，当前 4096）
        为准。超限时依次：砍历史 → 截断 system 上下文，保证 max_tokens >= 1。
        """
        try:
            messages = [m for m in messages if m.get("content")]
            ctx_limit = LLM_MAX_MODEL_LEN  # 与 start.sh 的 max_model_len 保持一致

            def _estimate(msgs):
                chars = sum(len(m.get("content", "")) for m in msgs)
                return int(chars / 0.75)  # 中文约 1 字 ≈ 1 token，偏保守按 0.75 字/token

            estimated_input_tokens = _estimate(messages)
            safe_max_tokens = min(max_tokens, ctx_limit - estimated_input_tokens - 50)

            if safe_max_tokens < 256:
                # 第一刀：砍历史，只保留 system + 最近几轮
                messages = self._trim_messages(messages)
                estimated_input_tokens = _estimate(messages)
                safe_max_tokens = min(max_tokens, ctx_limit - estimated_input_tokens - 50)

            if safe_max_tokens < 256:
                # 第二刀：system 太长（附件/知识库/模板注入过多），截断 system 本体
                messages = self._shrink_system(messages, ctx_limit)
                estimated_input_tokens = _estimate(messages)
                safe_max_tokens = min(max_tokens, ctx_limit - estimated_input_tokens - 50)

            if safe_max_tokens < 1:
                # 极端兜底：只保留 system（截断后）+ 当前用户消息
                messages = self._trim_messages(messages, keep_rounds=1)
                messages = self._shrink_system(messages, ctx_limit)
                estimated_input_tokens = _estimate(messages)
                safe_max_tokens = max(1, min(256, ctx_limit - estimated_input_tokens - 50))

            print(f"[vLLM请求] 估算输入: ~{estimated_input_tokens} tokens, max_tokens: {safe_max_tokens}")

            response = requests.post(
                f"{self.api_url}/chat/completions",
                headers={"Content-Type": "application/json"},
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": safe_max_tokens,
                    "top_p": 0.9
                },
                timeout=300
            )
            response.raise_for_status()
            result = response.json()

            choice = result["choices"][0]
            print(f"[vLLM返回] finish_reason: {choice.get('finish_reason')}, usage: {result.get('usage')}")
            if choice.get("finish_reason") == "length":
                print("⚠️ 输出被 max_tokens 截断")

            return choice["message"]["content"]

        except requests.exceptions.ConnectionError:
            return "【系统错误】vLLM 服务未启动，请检查 http://localhost:8001"
        except requests.exceptions.HTTPError as e:
            detail = e.response.text if e.response is not None else str(e)
            print("[vLLM错误]", detail)
            return f"调用模型失败: {detail}"
        except Exception as e:
            return f"调用模型失败: {str(e)}"
    def _trim_messages(self, messages: List[Dict], keep_rounds: int = 3) -> List[Dict]:
        """输入太长时，只保留 system + 最近几轮对话"""
        system = [m for m in messages if m.get("role") == "system"][:1]
        others = [m for m in messages if m.get("role") != "system"]
        return system + others[-keep_rounds * 2:]
    def _shrink_system(self, messages: List[Dict], ctx_limit: int) -> List[Dict]:
        """system 上下文（附件材料/知识库/参考模板）过长时，按比例截断，
        给历史对话和输出留出空间。"""
        system = [m for m in messages if m.get("role") == "system"]
        others = [m for m in messages if m.get("role") != "system"]
        if not system:
            return messages
        # system 最多占上下文的一半字符预算
        sys_char_budget = int((ctx_limit - 512) * 0.75 * 0.5)
        content = system[0].get("content", "")
        if len(content) > sys_char_budget:
            content = content[:sys_char_budget] + "\n（上下文过长，参考材料已按长度截断）"
        return [{"role": "system", "content": content}] + others
    def _detect_intent(self, message: str) -> str:
        """检测用户意图"""
        msg = message.lower()

        if any(k in msg for k in ["查", "第几条", "是什么", "规定", "条款", "内容", "细则"]):
            return "search"
        if any(k in msg for k in ["写", "起草", "生成", "撰写"]):
            return "writing"
        if any(k in msg for k in ["总结", "概括", "摘要"]):
            return "summary"
        if any(k in msg for k in ["润色", "修改", "改写"]):
            return "rewrite"

        return "chat"

    def _detect_doc_type(self, message: str) -> str:
        """检测公文类型"""
        msg = message.lower()

        # 请示必须先于报告判断："请示"是文种意图，请示正文里常出现"报告"字样
        if "请示" in msg:
            return "request"
        if "报告" in msg:
            return "report"
        if "通知" in msg:
            return "notification"
        if any(k in msg for k in ["外宣", "宣传", "推文", "公众号", "新闻稿", "报道", "案例宣传"]):
            return "publicity"
        if "总结" in msg:
            return "summary"
        if "方案" in msg:
            return "plan"
        if "意见" in msg:
            return "opinion"

        return "notification"

    def chat(self, message: str, history: List[Dict], sources: List[Dict], user_role: str,
             memories: List[Dict] = None, examples: list = None,
             system_prompt: str = None, template_category: str = None,
             attachment_context: str = None,
             reference_template: Dict = None,
             task_reference_context: str = None,
             template_reference_context: str = None) -> str:
        """主对话入口

        attachment_context: 用户上传附件解析后的材料文本（由 AttachmentService 构建），
        作为独立的 system 内容注入，使模型在写作时真正基于材料。

        reference_template: 对话中选择的"参考模板"（WritingTemplate 字典），
        作为写作结构与风格约束注入，不限制用户必须填表。
        """
        intent = self._detect_intent(message)

        # 把知识库检索结果组装为资料块（写作和问答可复用）
        sources_block = ""
        if sources:
            docs = "\n\n".join(f"[参考资料{i+1}]\n{s['content'][:1200]}" for i, s in enumerate(sources))
            sources_block = (
                "\n\n以下是从单位知识库检索到的资料，写作/回答时应优先使用其中与主题相关的内容，"
                "引用其中的事实和数据；不相关的资料请忽略：\n" + docs
            )

        # 构建 system prompt：写作意图优先，知识库资料叠加注入
        if system_prompt:
            # 模板生成模式：使用模板自带的 system_prompt，叠加范文参考
            if examples:
                refs = "\n\n".join(
                    f"【范文{i+1}：{e['title']}】\n{e['content']}" for i, e in enumerate(examples)
                )
                system_prompt = f"{system_prompt}\n\n请严格模仿以下本单位范文的风格来写作：\n\n{refs}\n\n模仿要求：1. 结构层次与范文一致（标题、主送机关、正文分条、落款、成文日期）；2. 沿用范文的称谓、固定套语、过渡句和用词习惯；3. 保持相同的行文口吻和正式程度；4. 只替换成与本次主题相关的内容，范文里具体的单位名、人名、数字、日期不要照搬。\n\n请据此撰写，不要输出解释性文字，直接给公文正文。"
            system_prompt += sources_block
        elif intent == "writing" or reference_template:
            # 写作：写作规则优先，知识库资料作为素材注入
            system_prompt = self._build_writing_prompt(message, examples or []) + sources_block
        elif intent == "search":
            system_prompt = self._render_prompt(
                "search/legal_query",
                query=message,
                retrieved_docs=sources
            )
        else:
            system_prompt = self._default_prompt(sources=sources)
        # 注入对话级参考模板（信息写作中选择"参考模板"后持续生效）
        if reference_template:
            system_prompt += "\n\n" + self._build_reference_template_context(reference_template)

        # 注入"当前任务佐证材料"（事实依据，优先级最高；来自模板中心，不进知识库）
        if task_reference_context:
            system_prompt += "\n\n" + task_reference_context

        # 注入"模板固定参考材料"（风格范式，仅用于模仿写法，严禁照搬事实）
        if template_reference_context:
            system_prompt += "\n\n" + template_reference_context

        # 注入用户上传的附件材料（多轮对话中持续有效）
        if attachment_context:
            system_prompt += (
                "\n\n以下是用户上传的参考材料。用户接下来的要求（如整理、提炼、改写、模仿格式重写）"
                "均应基于这些材料完成；回答中涉及的事实、数据、名称以材料为准，不要虚构：\n\n"
                + attachment_context
            )

        # 构建消息列表
        messages = [{"role": "system", "content": system_prompt}]

        # 添加历史对话（最多20轮）
        for h in history[-20:]:
            messages.append({"role": h["role"], "content": h["content"]})

        # 当前用户问题
        messages.append({"role": "user", "content": message})

        # 调用模型
        return self._call_vllm(messages)

    def generate_document(self, doc_type: str, topic: str, references: str = "", style: str = "严谨", word_count: int = 1000) -> str:
        """直接生成公文"""
        prompt = self._render_prompt(
            f"writing/{doc_type}",
            topic=topic,
            references=references,
            style=style,
            word_count=word_count
        )

        messages = [
            {"role": "system", "content": "你是司法局公文写作专家。"},
            {"role": "user", "content": prompt}
        ]

        return self._call_vllm(messages, max_tokens=8192)
