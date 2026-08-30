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
        # 提示词要求 JSON 输出时返回可解析的最小结果，保证下游解析逻辑可测试
        if "JSON" in last_user or "json" in last_user:
            # PPT 大纲：需要含 slides 数组的 JSON 对象
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
            # 要求返回 JSON 数组
            if re.search(r"JSON\s*数组|\[\{", last_user):
                return "[]"
            return json.dumps(
                {"meeting_name": "（Mock）提取的会议名称", "meeting_time": "下周三上午"},
                ensure_ascii=False,
            )
        return f"（Mock 模型回复）已收到您的请求：{last_user[:200]}"
