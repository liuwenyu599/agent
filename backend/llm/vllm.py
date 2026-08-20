import requests
from typing import List, Dict

from backend.config.settings import VLLM_URL, LLM_MODEL

class VLLMClient:
    def __init__(self):
        self.api_url = VLLM_URL
        self.model = LLM_MODEL
    
    def chat(self, messages: List[Dict], temperature: float = 0.3, max_tokens: int = 1024) -> str:
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
            return None  # vLLM 未启动，让上层 fallback
        except requests.exceptions.HTTPError as e:
            # 关键：打印 vLLM 返回的具体错误
            print("[vLLM错误]", e.response.text)
            return f"调用模型失败: {e.response.text}"
        except Exception as e:
            print("[vLLM错误]", str(e))
            return f"调用失败: {str(e)}"
