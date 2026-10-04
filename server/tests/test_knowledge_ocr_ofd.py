from __future__ import annotations

import asyncio
import zipfile
from pathlib import Path

from app.application.knowledge.document_ocr import KnowledgeDocumentExtractor
from app.core.config import settings


class FakeVisionGateway:
    model_name = "fake-vision"

    def __init__(self, reply: str = "识别后的正文") -> None:
        self.reply = reply
        self.calls = []

    async def acomplete(self, messages, temperature=0.7, max_tokens=4096):
        self.calls.append({
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        })
        return self.reply


def _plain_empty(path: Path, filename: str) -> str:
    return ""


def test_supported_upload_types_include_ofd_and_scan_images():
    expected = {".ofd", ".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
    assert expected.issubset(set(settings.SUPPORTED_DOC_TYPES))


def test_text_native_ofd_extracts_textcode_without_vision(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OCR_MIN_TEXT_CHARS", 1)
    ofd = tmp_path / "sample.ofd"
    xml = """<?xml version='1.0' encoding='UTF-8'?>
    <ofd:Page xmlns:ofd='http://www.ofdspec.org/2016'>
      <ofd:Content>
        <ofd:TextObject><ofd:TextCode>广州市白云区司法局</ofd:TextCode></ofd:TextObject>
        <ofd:TextObject><ofd:TextCode>关于开展行政复议工作的通知</ofd:TextCode></ofd:TextObject>
      </ofd:Content>
    </ofd:Page>
    """
    with zipfile.ZipFile(ofd, "w") as archive:
        archive.writestr("Doc_0/Pages/Page_0/Content.xml", xml)

    extractor = KnowledgeDocumentExtractor(vision_gateway=False)
    text, method = asyncio.run(extractor.extract(ofd, "sample.ofd", _plain_empty))

    assert method == "ofd_xml"
    assert "广州市白云区司法局" in text
    assert "行政复议工作的通知" in text


def test_image_upload_uses_vision_ocr_data_url(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OCR_ENABLED", True)
    monkeypatch.setattr(settings, "OCR_MAX_PAGES", 20)
    monkeypatch.setattr(settings, "OCR_MAX_TOKENS", 2048)
    image = tmp_path / "scan.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nFAKE")
    gateway = FakeVisionGateway("白云区司法局扫描件正文")
    extractor = KnowledgeDocumentExtractor(vision_gateway=gateway)

    text, method = asyncio.run(extractor.extract(image, "scan.png", _plain_empty))

    assert method == "vision_ocr"
    assert text == "白云区司法局扫描件正文"
    assert len(gateway.calls) == 1
    call = gateway.calls[0]
    assert call["temperature"] == 0.0
    assert call["max_tokens"] == 2048
    content = call["messages"][0]["content"]
    image_parts = [part for part in content if part.get("type") == "image_url"]
    assert len(image_parts) == 1
    assert image_parts[0]["image_url"]["url"].startswith("data:image/png;base64,")


def test_scan_style_ofd_falls_back_to_embedded_image_ocr(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OCR_ENABLED", True)
    monkeypatch.setattr(settings, "OCR_MIN_TEXT_CHARS", 80)
    ofd = tmp_path / "scan.ofd"
    with zipfile.ZipFile(ofd, "w") as archive:
        archive.writestr("Doc_0/Pages/Page_0/Content.xml", "<Page></Page>")
        archive.writestr("Doc_0/Res/image_1.png", b"\x89PNG\r\n\x1a\nFAKE")

    gateway = FakeVisionGateway("OFD 扫描页识别结果")
    extractor = KnowledgeDocumentExtractor(vision_gateway=gateway)
    text, method = asyncio.run(extractor.extract(ofd, "scan.ofd", _plain_empty))

    assert method == "ofd_vision_ocr"
    assert text == "OFD 扫描页识别结果"
    assert len(gateway.calls) == 1


def test_text_native_pdf_does_not_call_vision(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "OCR_MIN_TEXT_CHARS", 5)
    gateway = FakeVisionGateway("不应调用")
    extractor = KnowledgeDocumentExtractor(vision_gateway=gateway)
    pdf = tmp_path / "native.pdf"
    pdf.write_bytes(b"%PDF-fake")

    text, method = asyncio.run(extractor.extract(
        pdf,
        "native.pdf",
        lambda path, filename: "这是可复制的 PDF 正文",
    ))

    assert method == "pdf_text"
    assert text == "这是可复制的 PDF 正文"
    assert gateway.calls == []


def test_batch_import_uses_same_ocr_extractor_contract():
    source = (
        Path(__file__).parents[1]
        / "app" / "application" / "knowledge" / "task_queue.py"
    ).read_text(encoding="utf-8")
    assert "doc_service.extractor.extract(" in source
    assert '"extraction_method": extraction_method' in source
    assert "DocumentService()" not in source
