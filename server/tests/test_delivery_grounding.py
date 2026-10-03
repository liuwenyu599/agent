"""Acceptance guards for delivery-review P0-4/P0-6."""
from pathlib import Path

from app.application.shared.writing_assistant import WritingAssistant
from app.core.config import settings


class _Gateway:
    model_name = "mock"

    def complete(self, messages, temperature=None, max_tokens=None):
        return "ok"


def test_legal_prompt_never_instructs_model_to_use_its_own_knowledge():
    assistant = WritingAssistant(_Gateway())
    prompt = assistant._build_system_prompt(
        "行政复议申请期限是多少？",
        sources=[{"content": "与问题无关的内部材料"}],
    )
    assert "再用你自己的知识回答" not in prompt
    assert "不得因信息不足而拒绝回答" not in prompt
    assert "不得用模型记忆补充具体法条" in prompt or "不得用模型记忆补充具体政策事实" in prompt


def test_rag_delivery_defaults_are_strict():
    assert settings.RAG_SCORE_THRESHOLD >= 0.7
    assert settings.RAG_VECTOR_CANDIDATES >= 30
    assert settings.RAG_RERANK_ENABLED is True
    assert settings.RAG_RERANK_TOP_K == 3


def test_ofd_is_not_advertised_until_parser_exists():
    assert ".ofd" not in settings.SUPPORTED_DOC_TYPES


def test_production_embedding_default_matches_delivery_model_family():
    # The delivery report identifies bge-m3/1024d as production. A 512d bge-small default
    # can silently poison an existing index after a fresh deployment.
    assert "bge-m3" in Path(settings.EMBED_MODEL_PATH).name.lower()
