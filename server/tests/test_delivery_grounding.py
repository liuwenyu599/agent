"""Acceptance guards for delivery-review P0-4/P0-6."""
import shutil
import tempfile
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


def test_ofd_is_extractable_and_advertised_together():
    """.ofd 出现在支持列表的前提是解析器真的能用——两者必须同时成立。

    这条守卫最初写的是 ``test_ofd_is_not_advertised_until_parser_exists``：
    当时 .ofd 被列进 ``SUPPORTED_DOC_TYPES`` 却没有解析器，政务 OFD 上传直接 400。
    现在 ``KnowledgeDocumentExtractor`` 能直读 OFD ZIP 包里的 TextCode 节点，
    扫描型 OFD 还能走视觉 OCR，前提已经反转，故改为锁定"声明即实现"。

    这里真造一个最小 OFD（ZIP + TextCode 节点）跑一遍解析，而不是只反射查方法
    存在——方法名或实现坏了就该红，否则这道守卫会变成永远为真的摆设。
    """
    import zipfile

    from app.application.knowledge.document_ocr import KnowledgeDocumentExtractor

    tmp = Path(tempfile.mkdtemp(prefix="ofd-guard-"))
    try:
        ofd_path = tmp / "sample.ofd"
        with zipfile.ZipFile(ofd_path, "w") as archive:
            archive.writestr("OFD.xml", '<?xml version="1.0"?><ofd><body/></ofd>')
            archive.writestr(
                "Doc_0/Document.xml",
                '<?xml version="1.0"?><ofd><body><page>'
                "<TextCode>行政复议申请期限为六十日</TextCode>"
                "</page></body></ofd>",
            )
        text = KnowledgeDocumentExtractor()._extract_ofd_text(ofd_path)
        assert "行政复议申请期限" in text
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    assert ".ofd" in settings.SUPPORTED_DOC_TYPES


def test_production_embedding_default_matches_delivery_model_family():
    # The delivery report identifies bge-m3/1024d as production. A 512d bge-small default
    # can silently poison an existing index after a fresh deployment.
    assert "bge-m3" in Path(settings.EMBED_MODEL_PATH).name.lower()
