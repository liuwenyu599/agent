import json
import re
from typing import List, Dict, Optional

from jinja2 import Template


class IntentService:
    """写作意图的信息完整度判断（P1 智能写作整理）。

    核心原则（见项目总 Prompt 第七节）：
    - 用户只提供模糊需求时，AI 主动询问最关键的 2~3 个缺失信息；
    - 信息足够时直接生成，不机械提问；
    - 任何异常都回退为"直接生成"，不影响主流程稳定性。
    """

    # 触发"写作类"判断的关键词（与 llm_service._detect_intent 保持一致风格）
    WRITING_HINTS = [
        # 原有动作词
        "写", "撰写", "起草", "拟稿", "代写", "帮我写", "编写", "草拟",
        # 新增：名词型请求（用户常常不带"写"字）
        "文档", "材料", "汇报", "总结", "简报", "新闻稿", "讲话稿",
        "通知", "请示", "报告", "方案", "纪要", "函", "决定", "公告",
        "格式", "规范", "公文", "稿件", "文稿", "正式版", "完整版",
        "给我一份", "生成一份", "出一份", "整理成",
    ]

    # 信息完整度判断的提示词（优先读 prompts/write/clarify.jinja2，缺失时用内置默认）
    _DEFAULT_CLARIFY_PROMPT = """你是司法行政单位办公助手的需求分析模块。用户想写一篇材料，请判断用户已提供的信息是否足以起草一篇真实、不虚构的初稿。

用户输入：
{{ message }}
{% if reference_template_name %}
参考文种：{{ reference_template_name }}
{% endif %}

判断规则：
1. 起草一篇真实材料通常需要：什么事情（主题/事项）、时间、地点或单位、涉及人员/对象、主要经过或内容要点。
2. 用户已明确给出的信息不要重复询问；常识性、可由用户后续修改的要素（如具体措辞、结构）不算缺失。
3. 只询问对成稿影响最大的缺失信息，最多 3 个，每个一句话。
4. 如果信息基本足够（能写出一篇不需要虚构事实的草稿），判定为 ready。

只输出 JSON，不要输出任何其他内容：
{"ready": true}
或
{"ready": false, "questions": ["问题1", "问题2", "问题3"]}"""

    def __init__(self, llm_service):
        self.llm = llm_service

    def _render_clarify_prompt(self, message: str, reference_template_name: str = None) -> str:
        template_str = self.llm.prompts.get("write/clarify") or self._DEFAULT_CLARIFY_PROMPT
        return Template(template_str).render(
            message=message,
            reference_template_name=reference_template_name,
        )

    def _looks_like_writing(self, message: str) -> bool:
        return any(k in message for k in self.WRITING_HINTS)

    def _last_assistant_was_asking(self, history: List[Dict]) -> bool:
        """上一轮 AI 在提问时，本轮视为用户在补充信息，不再重复询问。"""
        for h in reversed(history or []):
            if h.get("role") == "assistant":
                tail = (h.get("content") or "")[-300:]
                return "？" in tail or "?" in tail
            if h.get("role") == "user":
                return False
        return False

    def check_writing_clarification(
        self,
        message: str,
        history: List[Dict],
        has_materials: bool,
        reference_template: Optional[Dict] = None,
    ) -> Optional[str]:
        """判断是否需要先向用户提问。

        返回 None 表示直接生成；返回字符串表示给用户的提问回复。
        """
        try:
            if not self._looks_like_writing(message):
                return None
            # 已有附件材料：信息来源充足，直接生成
            if has_materials:
                return None
            # 上一轮 AI 在提问：本轮是用户在回答，直接生成
            if self._last_assistant_was_asking(history):
                return None

            tmpl_name = reference_template.get("name") if reference_template else None
            prompt = self._render_clarify_prompt(message, tmpl_name)

            raw = self.llm._call_vllm(
                [
                    {"role": "system", "content": "你是需求分析模块，只输出 JSON。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=300,
            )
            if not raw or raw.startswith("【系统错误】") or raw.startswith("调用模型失败"):
                return None

            m = re.search(r"\{.*\}", raw, re.S)
            if not m:
                return None
            result = json.loads(m.group(0))

            if result.get("ready"):
                return None

            questions = [q.strip() for q in (result.get("questions") or []) if q and q.strip()][:3]
            if not questions:
                return None

            doc_hint = f"这篇{tmpl_name}" if tmpl_name else "这篇材料"
            lines = [f"可以，我可以先帮您起草{doc_hint}。为了让内容准确完整，还需要确认几个关键信息："]
            lines += [f"{i+1}. {q}" for i, q in enumerate(questions)]
            lines.append("如果有相关通知、方案、记录或现场照片等材料，也可以直接上传，我会根据材料起草。")
            return "\n".join(lines)

        except Exception as e:
            # 任何异常都不阻断主流程
            print(f"[Intent] 信息完整度判断失败，回退为直接生成: {e}")
            return None