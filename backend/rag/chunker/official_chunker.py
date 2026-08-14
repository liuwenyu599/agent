import re
from typing import List, Dict

class OfficialChunker:
    """公文文档切片器：按标题层级切分"""
    
    def chunk(self, text: str, doc_id: str) -> List[Dict]:
        pattern = r'([一二三四五六七八九十]+[、．.]\s*|（[一二三四五六七八九十]+）\s*|\d+[\.．]\s*|（\d+）\s*)(.*?)(?=([一二三四五六七八九十]+[、．.]\s*|（[一二三四五六七八九十]+）\s*|\d+[\.．]\s*|（\d+）\s*)|$)'
        
        matches = re.findall(pattern, text, re.DOTALL)
        
        chunks = []
        for i, match in enumerate(matches):
            heading = match[0].strip()
            content = match[1].strip()
            
            if len(content) > 20:
                chunks.append({
                    "chunk_index": i,
                    "chunk_type": "section",
                    "title": heading,
                    "content": f"{heading} {content}",
                    "metadata": {
                        "heading": heading,
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
