from typing import Any, Dict, List
from .base import BaseTool

class LawTool(BaseTool):
    name = "law_query"
    description = "查询法律条文、法规规定"
    
    def execute(self, query: str, top_k: int = 5) -> List[Dict]:
        # TODO: 实际调用 RAG
        return [{"content": "模拟法律条文", "source": "模拟"}]
    
    def get_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "查询内容"},
                "top_k": {"type": "integer", "description": "返回条数"}
            },
            "required": ["query"]
        }
