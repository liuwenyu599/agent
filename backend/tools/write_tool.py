from typing import Any, Dict
from .base import BaseTool

class WriteTool(BaseTool):
    name = "write_document"
    description = "撰写公文材料（通知、报告、请示、总结、方案等）"
    
    def execute(self, doc_type: str, topic: str, references: str = "", style: str = "严谨", word_count: int = 1000) -> str:
        return f"需要撰写{doc_type}：{topic}，风格：{style}，字数：{word_count}，参考：{references}"
    
    def get_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "doc_type": {"type": "string", "enum": ["通知", "报告", "请示", "总结", "方案", "意见"]},
                "topic": {"type": "string", "description": "主题"},
                "references": {"type": "string", "description": "参考内容"},
                "style": {"type": "string", "description": "写作风格"},
                "word_count": {"type": "integer", "description": "字数要求"}
            },
            "required": ["doc_type", "topic"]
        }
