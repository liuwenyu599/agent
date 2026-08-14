import os
import json
import requests
from typing import List, Dict, Optional
from jinja2 import Template

from backend.config.settings import VLLM_URL, LLM_MODEL

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
        parts = ["你是司法局智能助手，擅长公文写作与法律法规问答。请优先结合对话历史理解用户意图，回答准确、简洁、有条理。"]

        if sources:
            docs = "\n\n".join(f"[参考资料{i+1}]\n{s['content'][:1200]}" for i, s in enumerate(sources))
            parts.append(
                "以下是检索到的参考资料，若与问题相关请据此作答；若不相关请忽略，直接用你自己的知识回答：\n" + docs
            )

        return "\n\n".join(parts)

    def _build_writing_prompt(self, topic: str, examples: list) -> str:
        if not examples:
            return "你是司法局公文写作专家，请按规范的党政机关公文格式撰写，结构完整、行文严谨。"

        refs = "\n\n".join(
            f"【范文{i+1}：{e['title']}】\n{e['content']}" for i, e in enumerate(examples)
        )
        return f"""你是司法局公文写作专家。请**严格模仿本单位范文**的风格来写作。

模仿要求：
1. 结构层次与范文一致（标题、主送机关、正文分条、落款、成文日期）；
2. 沿用范文的称谓、固定套语、过渡句和用词习惯；
3. 保持相同的行文口吻和正式程度；
4. 只替换成与本次主题相关的内容，范文里具体的单位名、人名、数字、日期不要照搬。

{refs}

请据此撰写，不要输出解释性文字，直接给公文正文。"""

    def _call_vllm(self, messages: List[Dict], temperature: float = 0.3, max_tokens: int = 2048) -> str:
        """调用 vLLM 服务（OpenAI 兼容 API）"""
        try:
            response = requests.post(
                f"{self.api_url}/chat/completions",
                headers={"Content-Type": "application/json"},
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "top_p": 0.8
                },
                timeout=120
            )
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"]
        except requests.exceptions.ConnectionError:
            return "【系统错误】vLLM 服务未启动，请检查 http://localhost:8001"
        except Exception as e:
            return f"调用模型失败: {str(e)}"

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

        if "通知" in msg:
            return "notification"
        if "报告" in msg:
            return "report"
        if "请示" in msg:
            return "request"
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
             attachment_context: str = None) -> str:
        """主对话入口

        attachment_context: 用户上传附件解析后的材料文本（由 AttachmentService 构建），
        作为独立的 system 内容注入，使模型在写作时真正基于材料。
        """

        intent = self._detect_intent(message)

        # 构建 system prompt
        if system_prompt:
            # 模板生成模式：使用模板自带的 system_prompt，叠加范文参考
            if examples:
                refs = "\n\n".join(
                    f"【范文{i+1}：{e['title']}】\n{e['content']}" for i, e in enumerate(examples)
                )
                system_prompt = f"{system_prompt}\n\n请严格模仿以下本单位范文的风格来写作：\n\n{refs}\n\n模仿要求：1. 结构层次与范文一致（标题、主送机关、正文分条、落款、成文日期）；2. 沿用范文的称谓、固定套语、过渡句和用词习惯；3. 保持相同的行文口吻和正式程度；4. 只替换成与本次主题相关的内容，范文里具体的单位名、人名、数字、日期不要照搬。\n\n请据此撰写，不要输出解释性文字，直接给公文正文。"
        elif sources:
            system_prompt = self._default_prompt(sources=sources)
        elif intent == "search":
            system_prompt = self._render_prompt(
                "search/legal_query",
                query=message,
                retrieved_docs=sources
            )
        elif intent == "writing":
            system_prompt = self._build_writing_prompt(message, examples or [])
        else:
            system_prompt = self._default_prompt(sources=sources)

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

        return self._call_vllm(messages, max_tokens=2048)
