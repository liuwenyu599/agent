"""写作意图的信息完整度判断（移植自旧 services/intent_service.py）。

- 用户只提供模糊需求时，主动询问最关键的 2~3 个缺失信息；
- 信息足够时直接生成，不机械提问；
- 任何异常都回退为"直接生成"，不影响主流程稳定性。

路由原则（治"分不清动作和询问、答非所问"）：
- 主判据是"有没有动作"（强动作动词），不是"有没有文种词"；
- WRITING_HINTS 保留作兜底弱线索，不再单独当判据；
- 疑问形式且没有明确指令口吻 → 一律当提问直接答；
- 宁可当提问直接答，也不要误当指令去改东西。
"""
import json
import re
from typing import Dict, List, Optional

from jinja2 import Template

from app.application.shared.writing_assistant import WritingAssistant
from app.core.logging import get_logger

logger = get_logger(__name__)


class IntentService:
    # 强动作动词：出现才可能是"要产出/修改内容"
    ACTION_HINTS = (
        "写", "起草", "撰写", "拟稿", "代写", "编写", "草拟",
        "生成", "出一份", "给我一份", "整理成",
        "扩写", "润色", "精简", "改写", "修改", "改成", "删除",
        "删掉", "导出", "换成", "调整为", "加上", "补一段",
    )

    # 弱线索：保留作兜底，必须与指令口吻同时出现才算写作意图
    WRITING_HINTS = (
        "拟", "文档", "材料", "汇报", "总结", "简报", "新闻稿", "讲话稿",
        "通知", "请示", "报告", "方案", "纪要", "函", "决定", "公告",
        "格式", "规范", "公文", "稿件", "文稿", "正式版", "完整版",
    )

    # 疑问特征：命中且没有指令口吻时，按只读问答处理
    _QUESTION_WORDS = ("什么", "怎么", "怎么样", "如何", "哪些", "哪个",
                       "哪里", "多久", "多少", "几", "吗", "呢")

    # 指令口吻：疑问句里带这些词，仍是 workspace 指令（"能不能帮我改成 2000 字？"）
    _IMPERATIVE_WORDS = ("帮我", "请", "给我", "麻烦", "把", "按")

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

    def __init__(self, assistant: WritingAssistant) -> None:
        self.assistant = assistant

    def _render_clarify_prompt(self, message: str, reference_template_name: str = None) -> str:
        template_str = self.assistant.prompts.get("write/clarify") or self._DEFAULT_CLARIFY_PROMPT
        return Template(template_str).render(
            message=message,
            reference_template_name=reference_template_name,
        )

    # ---- 路由判定 ----

    def is_writing_request(self, message: str) -> bool:
        """主判据：这条消息是否"要在工作台产出/修改内容"。

        - 没有强动作动词 → 兜底看弱线索+指令口吻；
        - 疑问形式且没有指令口吻 → False（只读问答）；
        - 宁可漏判为提问直接答，也不要误判为指令去改东西。
        """
        m = (message or "").strip()
        if not m:
            return False
        has_action = any(k in m for k in self.ACTION_HINTS)
        has_imperative = any(k in m for k in self._IMPERATIVE_WORDS)
        if not has_action:
            # 兜底：弱线索（文种词/拟）必须配指令口吻才算 workspace
            if not (has_imperative and any(k in m for k in self.WRITING_HINTS)):
                return False
        is_question = (
            "？" in m or "?" in m
            or any(w in m for w in self._QUESTION_WORDS)
        )
        if is_question and not has_imperative:
            return False
        return True

    def _looks_like_writing(self, message: str) -> bool:
        """保留旧接口名，内部已切换为 side_effect 主判据。"""
        return self.is_writing_request(message)

    @staticmethod
    def _last_assistant_was_asking(history: List[Dict]) -> bool:
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
        """返回 None 表示直接生成；返回字符串表示给用户的提问回复。"""
        try:
            if not self.is_writing_request(message):
                return None
            if has_materials:
                return None
            if self._last_assistant_was_asking(history):
                return None

            tmpl_name = reference_template.get("name") if reference_template else None
            prompt = self._render_clarify_prompt(message, tmpl_name)

            raw = self.assistant.complete(
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
            logger.warning("[Intent] 信息完整度判断失败，回退为直接生成: %s", e)
            return None
