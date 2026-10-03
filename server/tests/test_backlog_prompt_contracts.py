from pathlib import Path

from app.application.shared.prompt_budget import compact_style_examples
from app.application.writing.grounded_task_service import GroundedWritingTaskService
from app.core.config import settings
from app.infrastructure.ai.qwen import QwenGateway


class _Rag:
    def __init__(self):
        self.query = None
        self.kwargs = None

    def search_examples(self, **kwargs):
        self.query = kwargs["query"]
        self.kwargs = kwargs
        return [{
            "title": "关于开展专项工作的通知",
            "content": "一、提高认识\n为进一步做好有关工作，现将事项通知如下。\n二、抓好落实\n请认真组织实施。",
        }]


def test_exemplar_query_explicitly_prioritizes_document_type():
    query = GroundedWritingTaskService._exemplar_query("请起草一份关于专项检查的通知")
    assert query.startswith("文种：通知\n同文种范文优先：通知\n")


def test_style_card_is_single_compact_example_and_not_full_article_dump():
    huge = "一、总体要求\n" + ("为进一步做好有关工作，现将有关事项通知如下。" * 200)
    cards = compact_style_examples([
        {"title": "通知范文", "content": huge},
        {"title": "第二篇不应进入", "content": "二、其他"},
    ])
    assert len(cards) <= 1100
    assert "一级结构骨架" in cards
    assert "固定用语/过渡句式" in cards
    assert "第二篇不应进入" not in cards


def test_production_prompt_budget_defaults_are_slimmed():
    assert settings.RAG_TOP_K == 3
    assert settings.RAG_CHUNK_MAX_CHARS <= 800
    assert settings.RAG_EXPAND_BUDGET <= 800


def test_qwen_payload_has_nontrivial_repetition_penalty():
    gateway = QwenGateway(api_url="http://example.test/v1")
    payload = gateway._base_payload([{"role": "user", "content": "x"}], 0.4, 128)
    assert 1.0 < payload["repetition_penalty"] <= 1.2


def test_deploy_examples_do_not_recommend_legacy_rag_top5():
    root = Path(__file__).resolve().parents[2]
    model_pool = (root / "deploy" / "model-pool.env.example").read_text(encoding="utf-8")
    assert "MODEL_SERVICE_URLS=" in model_pool
