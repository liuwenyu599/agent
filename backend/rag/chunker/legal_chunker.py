import re
from typing import List, Dict

class LegalChunker:
    """法规文档切片器：按条款切分"""
    
    def chunk(self, text: str, doc_id: str) -> List[Dict]:
        pattern = r'(第[一二三四五六七八九十百千零\d]+条[、\.]?\s*)(.*?)(?=(第[一二三四五六七八九十百千零\d]+条[、\.]?\s*)|$)'
        matches = re.findall(pattern, text, re.DOTALL)
        
        chunks = []
        for i, match in enumerate(matches):
            article_num = match[0].strip()
            content = match[1].strip()
            
            if len(content) > 10:
                chunks.append({
                    "chunk_index": i,
                    "chunk_type": "article",
                    "title": article_num,
                    "content": f"{article_num} {content}",
                    "metadata": {
                        "article_number": article_num,
                        "char_count": len(content),
                        "word_count": len(content)
                    }
                })
        
        if not chunks:
            return self._fallback_chunk(text, doc_id)
        
        return chunks
    
    def _fallback_chunk(self, text: str, doc_id: str) -> List[Dict]:
        chunks = []
        for i, para in enumerate(text.split("\n\n")):
            para = para.strip()
            if len(para) > 50:
                chunks.append({
                    "chunk_index": i,
                    "chunk_type": "paragraph",
                    "title": "",
                    "content": para,
                    "metadata": {
                        "char_count": len(para),
                        "word_count": len(para)
                    }
                })
        return chunks
