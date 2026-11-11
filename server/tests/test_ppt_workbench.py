"""PPT 工作台新增服务端端点测试（materials/analyze、documents/import、
outline/stream、ai/slide-action、ai/visual、ai/structure）。

运行方式（在 server/ 目录下）：
    D:/apps/anaconda3/python.exe -m pytest tests/test_ppt_workbench.py -v

测试策略：
- **模型一律打桩**：本地 8001 通用模型与 8003 PPT 专用模型均未启动，测试用
  monkeypatch 替换 `app.infrastructure.ai.get_ppt_gateway` 与
  `app.interfaces.ppt.get_llm_gateway`，返回可控的 FakeGateway。
  本文件**不验证模型输出质量**，只验证不依赖模型的部分：
  参数校验 / 鉴权与越权 / 缺失资源 404 / SSE 事件骨架与顺序 /
  pptx 解析出的大纲结构 / sources(provenance) 字段的存在与结构。
- **数据隔离**：DATA_DIR 与 DATABASE_URL 指向临时目录，绝不写入真实库。
"""
import io
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest
from app.core.exceptions import AppError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("AI_PROVIDER", "mock")

_TMPDIR = Path(tempfile.mkdtemp(prefix="test-ppt-"))
os.environ.setdefault("DATA_DIR", str(_TMPDIR))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{(_TMPDIR / 'test.db').as_posix()}")

from fastapi.testclient import TestClient  # noqa: E402

from app.application.ppt.service import PPTService  # noqa: E402
from app.application.ppt import ppt_engine  # noqa: E402
from app.infrastructure.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

Base.metadata.create_all(bind=engine)

BASE = "/api/v1"
PWD = "Passw0rd!2026"


# ============================================================ 模型打桩


class FakeGateway:
    """替身模型网关：记录每次调用，按 responder 返回固定文本。

    只实现 WritingAssistant 用到的 complete()，不发任何网络请求。
    """

    def __init__(self, responder=None):
        self.calls = []
        self._responder = responder or (lambda messages: "{}")

    @property
    def model_name(self) -> str:
        return "fake-ppt-model"

    def complete(self, messages, temperature=0.7, max_tokens=4096):
        self.calls.append({"messages": messages,
                           "temperature": temperature,
                           "max_tokens": max_tokens})
        return self._responder(messages)

    @property
    def last_prompt(self) -> str:
        """最近一次调用的 user 消息文本（用于断言 prompt 侧要求是否下发）。"""
        return self.calls[-1]["messages"][-1]["content"]


@pytest.fixture
def fake_llm(monkeypatch):
    """把 PPT 专用网关与主文本网关都换成可控替身。"""
    import app.infrastructure.ai as ai_mod
    import app.interfaces.ppt as ppt_iface

    fake = FakeGateway()
    # PPT 专用网关（服务内 `from app.infrastructure.ai import get_ppt_gateway` 惰性取用）
    monkeypatch.setattr(ai_mod, "get_ppt_gateway", lambda: fake)
    # 主文本网关（接口层 get_ppt_service 注入 WritingAssistant 时使用）
    monkeypatch.setattr(ai_mod, "get_llm_gateway", lambda: fake)
    monkeypatch.setattr(ppt_iface, "get_llm_gateway", lambda: fake)
    # 清掉网关缓存，避免真实 QwenGateway 被构造
    ai_mod.reset_gateway()
    return fake


# ============================================================ 夹具


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _hdr(token):
    return {"Authorization": f"Bearer {token}"}


def _dev_token(client):
    """取得系统管理员令牌（首个用户已被占用时直接为库内管理员签发）。"""
    r = client.post(f"{BASE}/auth/register-first", json={
        "username": "pptdev", "email": "pptdev@test.local",
        "password": PWD, "real_name": "系统管理员",
    })
    if r.status_code == 200:
        return r.json()["access_token"]

    from sqlalchemy import select

    from app.core.security import create_access_token
    from app.infrastructure.database import SessionLocal
    from app.infrastructure.database.models.identity import UserModel

    db = SessionLocal()
    try:
        row = db.scalar(select(UserModel).where(
            UserModel.role.in_(("developer", "admin"))))
        assert row is not None, "库中没有可用的系统管理员账号"
        return create_access_token(
            {"sub": row.id, "username": row.username, "role": row.role})
    finally:
        db.close()


def test_private_template_is_visible_only_to_owner(client, accounts):
    created = client.post(f"{BASE}/ppt/templates", headers=_hdr(accounts["a"]), json={
        "name": "甲的私有模板", "category": "汇报", "description": "仅本人可用",
    })
    assert created.status_code == 200, created.text
    template_id = created.json()["id"]

    owner = client.get(
        f"{BASE}/ppt/templates/{template_id}", headers=_hdr(accounts["a"]))
    assert owner.status_code == 200, owner.text

    other = client.get(
        f"{BASE}/ppt/templates/{template_id}", headers=_hdr(accounts["b"]))
    assert other.status_code == 404
    favorite = client.post(
        f"{BASE}/ppt/templates/{template_id}/favorite", headers=_hdr(accounts["b"]))
    assert favorite.status_code == 404
    blank = client.post(f"{BASE}/ppt/blank", headers=_hdr(accounts["b"]), json={
        "title": "越权模板测试", "template_id": template_id,
    })
    assert blank.status_code == 404


def test_template_configuration_is_validated_before_save(client, accounts):
    headers = _hdr(accounts["a"])
    invalid_color = client.post(f"{BASE}/ppt/templates", headers=headers, json={
        "name": "非法配色", "colors": {"primary": "red"},
    })
    assert invalid_color.status_code == 400
    invalid_layout = client.post(f"{BASE}/ppt/templates", headers=headers, json={
        "name": "非法版式", "layouts": {"content": "missing"},
    })
    assert invalid_layout.status_code == 400
    created = client.post(f"{BASE}/ppt/templates", headers=headers, json={
        "name": "有效模板", "colors": {"primary": "#17365d"},
        "layouts": {"content": "content.compare"},
    })
    assert created.status_code == 200, created.text
    detail = client.get(f"{BASE}/ppt/templates/{created.json()['id']}", headers=headers)
    assert detail.json()["colors"]["primary"] == "17365D"
    assert detail.json()["layouts"]["content"] == "content.compare"


def test_copied_uploaded_template_keeps_learned_layouts(client, accounts, monkeypatch):
    monkeypatch.setattr(PPTService, "_gen_tpl_previews", lambda *_args: None)
    data = _make_pptx_bytes([
        ("封面", []), ("工作安排", ["第一项", "第二项"]), ("结束", []),
    ])
    headers = _hdr(accounts["a"])
    uploaded = client.post(f"{BASE}/ppt/templates/upload", headers=headers,
                           data={"name": "自制版式", "category": "汇报"},
                           files={"file": ("layout.pptx", data,
                                           "application/vnd.openxmlformats-officedocument.presentationml.presentation")})
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["prepare_notes"]  # 上传即预处理已生效
    source_id = uploaded.json()["id"]
    copied = client.post(f"{BASE}/ppt/templates/{source_id}/copy", headers=headers)
    assert copied.status_code == 200, copied.text
    copy_id = copied.json()["id"]
    detail = client.get(f"{BASE}/ppt/templates/{copy_id}", headers=headers).json()
    assert detail["layout_count"] == uploaded.json()["layout_count"]
    assert detail["layout_library"]


def test_shared_pptx_template_requires_admin_and_license(client, accounts, monkeypatch):
    def fake_previews(svc, template_id, _data, layouts):
        for layout in layouts:
            if (layout.get("qualification") or {}).get("status") != "qualified":
                continue
            layout["source_preview"] = f"{layout['id']}.png"
            layout["preview"] = f"{layout['id']}-probe.png"
            for name in (layout["source_preview"], layout["preview"]):
                path = svc.ppt_dir / "tpl_prev" / template_id / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.setattr(PPTService, "_gen_tpl_previews", fake_previews)
    data = _make_pptx_bytes([("封面", []), ("工作安排", ["事项一", "事项二"])])
    files = {"file": ("licensed.pptx", data,
                       "application/vnd.openxmlformats-officedocument.presentationml.presentation")}
    endpoint = f"{BASE}/ppt/templates/upload"
    denied = client.post(endpoint, headers=_hdr(accounts["a"]),
                         data={"shared": "true", "license_note": "内部授权"}, files=files)
    assert denied.status_code == 403
    missing = client.post(endpoint, headers=_hdr(accounts["dev"]),
                          data={"shared": "true"}, files=files)
    assert missing.status_code == 400
    uploaded = client.post(endpoint, headers=_hdr(accounts["dev"]),
                           data={"shared": "true", "license_note": "允许内网重复生成及修改"},
                           files=files)
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["review_required"] is True
    template_id = uploaded.json()["id"]
    listing = client.get(f"{BASE}/ppt/templates", headers=_hdr(accounts["a"])).json()["items"]
    assert not any(item["id"] == template_id for item in listing)
    assert client.post(f"{BASE}/ppt/templates/{template_id}/publish",
                       headers=_hdr(accounts["a"])).status_code == 403
    published = client.post(f"{BASE}/ppt/templates/{template_id}/publish",
                            headers=_hdr(accounts["dev"]))
    assert published.status_code == 200, published.text
    listing = client.get(f"{BASE}/ppt/templates", headers=_hdr(accounts["a"])).json()["items"]
    assert any(item["id"] == template_id and item["is_learned"] for item in listing)


def test_second_admin_can_review_and_publish_pending_shared_template(
        client, accounts, monkeypatch):
    from sqlalchemy import select
    from app.core.security import create_access_token
    from app.infrastructure.database import SessionLocal
    from app.infrastructure.database.models.identity import UserModel

    def fake_previews(svc, template_id, _data, layouts):
        for layout in layouts:
            if (layout.get("qualification") or {}).get("status") != "qualified":
                continue
            layout["source_preview"] = f"{layout['id']}.png"
            layout["preview"] = f"{layout['id']}-probe.png"
            for name in (layout["source_preview"], layout["preview"]):
                path = svc.ppt_dir / "tpl_prev" / template_id / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"\x89PNG\r\n\x1a\n")

    monkeypatch.setattr(PPTService, "_gen_tpl_previews", fake_previews)
    data = _make_pptx_bytes([("封面", []), ("工作安排", ["事项一", "事项二"])])
    uploaded = client.post(f"{BASE}/ppt/templates/upload", headers=_hdr(accounts["dev"]),
                           data={"shared": "true", "license_note": "内网可复用"},
                           files={"file": ("shared.pptx", data,
                                           "application/vnd.openxmlformats-officedocument.presentationml.presentation")})
    assert uploaded.status_code == 200, uploaded.text
    template_id = uploaded.json()["id"]
    changed = client.put(f"{BASE}/ppt/templates/{template_id}",
                         headers=_hdr(accounts["dev"]), json={
                             "name": "待审党建模板", "category": "汇报",
                             "description": "已替换成业务说明，不再保留待审字样"})
    assert changed.status_code == 200, changed.text
    with SessionLocal() as db:
        reviewer = db.scalar(select(UserModel).where(UserModel.username == "pptuserb"))
        reviewer.role = "admin"
        db.commit()
        reviewer_id, reviewer_name = reviewer.id, reviewer.username
    try:
        token = create_access_token({"sub": reviewer_id,
                                     "username": reviewer_name, "role": "admin"})
        listed = client.get(f"{BASE}/ppt/templates?scope=pending",
                            headers=_hdr(token))
        assert listed.status_code == 200, listed.text
        assert any(item["id"] == template_id for item in listed.json()["items"])
        detail = client.get(f"{BASE}/ppt/templates/{template_id}", headers=_hdr(token))
        assert detail.status_code == 200 and detail.json()["license_note"] == "内网可复用"
        published = client.post(f"{BASE}/ppt/templates/{template_id}/publish",
                                headers=_hdr(token))
        assert published.status_code == 200, published.text
    finally:
        with SessionLocal() as db:
            reviewer = db.get(UserModel, reviewer_id)
            reviewer.role = "user"
            db.commit()


def test_missing_preview_renderer_is_explained_and_can_be_retried(client, accounts, monkeypatch):
    import app.application.ppt.service as ppt_service_module

    data = _make_pptx_bytes([
        ("封面", []), ("工作安排", ["第一项", "第二项"]),
    ])
    monkeypatch.setattr(ppt_service_module.shutil, "which", lambda _name: None)
    uploaded = client.post(f"{BASE}/ppt/templates/upload",
                           headers=_hdr(accounts["dev"]),
                           data={"shared": "true", "license_note": "内部授权使用"},
                           files={"file": ("layout.pptx", data,
                                           "application/vnd.openxmlformats-officedocument.presentationml.presentation")})
    assert uploaded.status_code == 200, uploaded.text
    assert "soffice" in uploaded.json()["preview_error"]
    template_id = uploaded.json()["id"]
    blocked = client.post(f"{BASE}/ppt/templates/{template_id}/publish",
                          headers=_hdr(accounts["dev"]))
    assert blocked.status_code == 503 and "soffice" in blocked.text
    retry = client.post(f"{BASE}/ppt/templates/{template_id}/refresh-preview",
                        headers=_hdr(accounts["dev"]))
    assert retry.status_code == 503 and "soffice" in retry.text


def test_legacy_template_can_be_rechecked_without_exposing_private_decks(
        client, accounts, monkeypatch):
    from app.infrastructure.database import SessionLocal
    from app.infrastructure.database.models.ppt import PPTTemplateModel

    monkeypatch.setattr(PPTService, "_gen_tpl_previews", lambda *_args: None)
    data = _make_pptx_bytes([("工作安排", ["事项一", "事项二"])])
    uploaded = client.post(f"{BASE}/ppt/templates/upload", headers=_hdr(accounts["a"]),
                           files={"file": ("legacy.pptx", data,
                                           "application/vnd.openxmlformats-officedocument.presentationml.presentation")})
    assert uploaded.status_code == 200, uploaded.text
    template_id = uploaded.json()["id"]
    with SessionLocal() as db:
        row = db.get(PPTTemplateModel, template_id)
        row.layout_library = [{key: value for key, value in layout.items()
                               if key != "qualification"}
                              for layout in row.layout_library]
        db.commit()
    detail = client.get(f"{BASE}/ppt/templates/{template_id}",
                        headers=_hdr(accounts["a"]))
    assert detail.json()["needs_recheck"] is True
    denied = client.post(f"{BASE}/ppt/templates/{template_id}/recheck",
                         headers=_hdr(accounts["b"]))
    assert denied.status_code == 403
    checked = client.post(f"{BASE}/ppt/templates/{template_id}/recheck",
                          headers=_hdr(accounts["a"]))
    assert checked.status_code == 200, checked.text
    assert client.get(f"{BASE}/ppt/templates/{template_id}",
                      headers=_hdr(accounts["a"])).json()["needs_recheck"] is False


def test_cover_only_private_template_is_kept_as_theme(client, accounts, monkeypatch):
    monkeypatch.setattr(PPTService, "_gen_tpl_previews", lambda *_args: None)
    data = _make_pptx_bytes([("封面标题", [])])
    uploaded = client.post(f"{BASE}/ppt/templates/upload", headers=_hdr(accounts["a"]),
                           files={"file": ("cover.pptx", data,
                                           "application/vnd.openxmlformats-officedocument.presentationml.presentation")})
    assert uploaded.status_code == 200, uploaded.text
    assert "仅使用配色、字体与母版" in uploaded.json()["message"]
    detail = client.get(f"{BASE}/ppt/templates/{uploaded.json()['id']}",
                        headers=_hdr(accounts["a"]))
    assert detail.status_code == 200
    assert detail.json()["is_theme_only"] is True
    assert detail.json()["is_learned"] is False
    template = {
        "colors": detail.json()["colors"], "font": detail.json()["font"],
        "layouts": detail.json()["layouts"], "layout_library": detail.json()["layout_library"]}
    output = ppt_engine.render_pptx({"slides": [{"type": "content",
        "title": "新稿", "points": ["内容完整"]}]}, template, base_pptx=data)
    from pptx import Presentation
    page = Presentation(io.BytesIO(output)).slides[0]
    assert "内容完整" in " ".join(shape.text for shape in page.shapes if shape.has_text_frame)


def test_fallback_keeps_uploaded_slide_master_but_removes_example_pages():
    from pptx import Presentation
    source = _make_pptx_bytes([("示例标题", ["示例正文"])])
    original = Presentation(io.BytesIO(source))
    design = ppt_engine.template_to_dict(ppt_engine.BUILTIN_TEMPLATES[0])
    output = Presentation(io.BytesIO(ppt_engine.build_pptx(
        {"slides": [{"type": "content", "title": "正式标题", "points": ["正式正文"]}]},
        design, base_pptx=source)))
    assert (output.slide_width, output.slide_height) == (
        original.slide_width, original.slide_height)
    assert len(output.slide_masters) == len(original.slide_masters)
    text = " ".join(shape.text for slide in output.slides for shape in slide.shapes
                    if shape.has_text_frame)
    assert "正式正文" in text and "示例正文" not in text


def test_public_gallery_requires_license_and_respects_selection(client, accounts):
    from PIL import Image
    from app.infrastructure.database import SessionLocal
    from app.infrastructure.database.models.identity import UserModel
    from sqlalchemy import select

    image = io.BytesIO()
    Image.new("RGB", (640, 360), "#345678").save(image, format="PNG")
    files = {"file": ("meeting.png", image.getvalue(), "image/png")}
    endpoint = f"{BASE}/ppt/library/images"
    data = {"name": "调解会议", "category": "调解", "caption": "基层调解会议现场",
            "source": "单位自摄", "license_note": "允许本系统内部使用和修改"}
    assert client.post(endpoint, headers=_hdr(accounts["a"]),
                       data=data, files=files).status_code == 403
    assert client.post(endpoint, headers=_hdr(accounts["dev"]),
                       data={**data, "license_note": ""}, files=files).status_code == 400
    uploaded = client.post(endpoint, headers=_hdr(accounts["dev"]),
                           data=data, files=files)
    assert uploaded.status_code == 200, uploaded.text
    image_id = uploaded.json()["id"]
    listed = client.get(f"{BASE}/ppt/materials", headers=_hdr(accounts["a"])).json()["items"]
    assert any(item["id"] == image_id and item["source"] == "library" for item in listed)
    assert client.get(f"{endpoint}/{image_id}/thumb",
                      headers=_hdr(accounts["a"])).content.startswith(b"\xff\xd8")
    db = SessionLocal()
    try:
        user = db.scalar(select(UserModel).where(UserModel.username == "pptusera"))
        svc = PPTService(db, None)
        assert [item["id"] for item in svc._user_images(user.id, [image_id])] == [image_id]
    finally:
        db.close()
    assert client.delete(f"{endpoint}/{image_id}", headers=_hdr(accounts["dev"])).status_code == 200
    assert client.get(f"{endpoint}/{image_id}/file",
                      headers=_hdr(accounts["a"])).status_code == 404


def test_official_template_has_real_cover_preview_when_renderer_available(client, accounts):
    import shutil
    if not shutil.which("soffice") or not shutil.which("pdftoppm"):
        pytest.skip("PPT preview renderer is unavailable")
    token = _hdr(accounts["a"])
    seeded = client.post(f"{BASE}/ppt/templates/seed", headers=token)
    assert seeded.status_code == 200, seeded.text
    listing = client.get(f"{BASE}/ppt/templates", headers=token)
    official = next(item for item in listing.json()["items"]
                    if item["is_official"] and not item.get("is_shared"))
    assert official["layout_count"] > 0
    preview = client.get(official["preview_url"], headers=token)
    assert preview.status_code == 200, preview.text
    assert preview.content.startswith(b"\x89PNG")


@pytest.fixture(scope="module")
def accounts(client):
    """系统管理员 + 两个互不相干的普通用户（用于越权断言）。"""
    dev = _dev_token(client)

    def reg(username):
        r = client.post(f"{BASE}/auth/register", json={
            "username": username, "email": f"{username}@test.local",
            "password": PWD, "department": "行政复议科", "role": "user",
        }, headers=_hdr(dev))
        assert r.status_code == 200, r.text
        tok = client.post(f"{BASE}/auth/login", json={
            "username": username, "password": PWD}).json()["access_token"]
        # 管理员代建的账号首登必须改密（真实业务流程）：未改密前业务端点一律 403
        changed = client.post(f"{BASE}/auth/change-password", json={
            "old_password": PWD, "new_password": "Changed@2026",
            "confirm_password": "Changed@2026",
        }, headers=_hdr(tok))
        assert changed.status_code == 200, changed.text
        return tok

    return {"dev": dev, "a": reg("pptusera"), "b": reg("pptuserb")}


# ============================================================ 工具


def _make_pptx_bytes(pages):
    """用 python-pptx 生成最小可解析 pptx：[(标题, [要点...]), ...]。"""
    from pptx import Presentation
    from pptx.util import Inches, Pt

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    blank = prs.slide_layouts[6]
    for title, bullets in pages:
        slide = prs.slides.add_slide(blank)
        tb = slide.shapes.add_textbox(Pt(50), Pt(40), Pt(600), Pt(70))
        tf = tb.text_frame
        tf.text = title
        if tf.paragraphs[0].runs:
            tf.paragraphs[0].runs[0].font.size = Pt(32)
        if bullets:
            tb2 = slide.shapes.add_textbox(Pt(50), Pt(150), Pt(600), Pt(320))
            tf2 = tb2.text_frame
            for i, b in enumerate(bullets):
                p = tf2.paragraphs[0] if i == 0 else tf2.add_paragraph()
                p.text = b
                if p.runs:
                    p.runs[0].font.size = Pt(18)
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def _parse_sse(text):
    """解析 SSE 响应体为事件列表。"""
    events = []
    for line in (text or "").splitlines():
        line = line.strip()
        if line.startswith("data:"):
            events.append(json.loads(line[len("data:"):].strip()))
    return events


def _blank_doc(client, token, title="测试PPT"):
    """建一个空白 PPT 文档，返回 doc_id。"""
    r = client.post(f"{BASE}/ppt/blank", json={"title": title}, headers=_hdr(token))
    assert r.status_code == 200, r.text
    return r.json()["doc_id"]


def _png_bytes(color=(28, 85, 140)):
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (320, 180), color).save(out, format="PNG")
    return out.getvalue()


# ============================================================ 1. materials/analyze


def test_outline_uses_only_explicitly_selected_library_materials(
        client, accounts, fake_llm, monkeypatch):
    headers = _hdr(accounts["a"])
    first = client.post(
        f"{BASE}/ppt/materials", headers=headers,
        data={"name": "社区矫正现场", "caption": "工作人员开展走访"},
        files={"file": ("scene.png", _png_bytes(), "image/png")},
    )
    second = client.post(
        f"{BASE}/ppt/materials", headers=headers,
        data={"name": "办公楼", "caption": "办公场所"},
        files={"file": ("office.png", _png_bytes((80, 90, 100)), "image/png")},
    )
    assert first.status_code == second.status_code == 200
    captured = {}

    def fake_generate(_assistant, _source_type, topic, _content, images,
                      slide_count, *_args, **_kwargs):
        captured["images"] = images
        return {"title": topic, "slides": [
            {"type": "cover", "title": topic},
            {"type": "content", "title": "工作情况", "points": ["依法履职"]},
            {"type": "closing", "title": "谢谢聆听"},
        ]}

    monkeypatch.setattr(ppt_engine, "generate_outline", fake_generate)
    monkeypatch.setattr(PPTService, "_audit_and_repair_outline",
                        lambda self, outline, *_args: outline)
    response = client.post(f"{BASE}/ppt/outline", headers=headers, json={
        "topic": "社区矫正工作汇报", "slide_count": 3,
        "material_ids": [first.json()["id"]],
    })
    assert response.status_code == 200, response.text
    assert [item["name"] for item in captured["images"]] == ["社区矫正现场"]
    assert response.json()["outline"]["material_ids"] == [first.json()["id"]]


def test_upload_image_uses_visual_description_when_caption_is_missing(
        client, accounts, monkeypatch):
    from app.application.ppt import image_analysis

    captured = {}

    class Vision:
        async def acomplete(self, messages, **_kwargs):
            captured["messages"] = messages
            return '{"caption":"群众在室内听工作人员讲解法律知识"}'

    monkeypatch.setattr(image_analysis, "get_vision_gateway", lambda: Vision())
    response = client.post(
        f"{BASE}/ppt/materials", headers=_hdr(accounts["a"]),
        data={"name": "自动识别测试"},
        files={"file": ("scene.png", _png_bytes(), "image/png")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["analysis_status"] == "ready"
    assert "群众" in response.json()["caption"]
    content = captured["messages"][0]["content"]
    assert any(item["type"] == "image_url" for item in content)
    listed = client.get(f"{BASE}/ppt/materials", headers=_hdr(accounts["a"]))
    assert any(item["caption"] == response.json()["caption"]
               for item in listed.json()["items"])


def test_upload_image_keeps_file_when_vision_is_unavailable(
        client, accounts, monkeypatch):
    from app.application.ppt import image_analysis

    monkeypatch.setattr(image_analysis, "get_vision_gateway", lambda: None)
    response = client.post(
        f"{BASE}/ppt/materials", headers=_hdr(accounts["a"]),
        data={"name": "待说明图片"},
        files={"file": ("scene.png", _png_bytes(), "image/png")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["analysis_status"] == "unavailable"
    assert response.json()["caption"] == ""
    assert "补写图片说明" in response.json()["message"]


def test_vision_caption_waits_for_slow_35b(monkeypatch):
    """35B 多模态首字延迟常超 15s；旧固定 15s 会让 caption 恒为空，
    图片随后被 _outline_images 过滤，表现为「传了图却从不自动配图」。"""
    import asyncio
    from app.application.ppt import image_analysis as ia

    class SlowVision:
        async def acomplete(self, messages, **_kwargs):
            await asyncio.sleep(0.05)
            return '{"caption":"室内普法宣讲现场"}'

    monkeypatch.setattr(ia, "get_vision_gateway", lambda: SlowVision())
    assert ia._CAPTION_TIMEOUT >= 60, "识图超时上限不能退回到 15s"
    assert asyncio.run(ia.describe_image(_png_bytes(), timeout=0.5)) == "室内普法宣讲现场"


def test_vision_caption_timeout_still_keeps_upload(monkeypatch):
    """识别超时不能拖垮上传：仍返回空 caption，由前端提示补写说明。"""
    import asyncio
    from app.application.ppt import image_analysis as ia

    class HangingVision:
        async def acomplete(self, messages, **_kwargs):
            await asyncio.sleep(5)
            return '{"caption":"不该返回"}'

    monkeypatch.setattr(ia, "get_vision_gateway", lambda: HangingVision())
    assert asyncio.run(ia.describe_image(_png_bytes(), timeout=0.05)) == ""


def test_image_caption_can_be_corrected_only_by_owner_or_admin(
        client, accounts, monkeypatch):
    from app.application.ppt import image_analysis

    monkeypatch.setattr(image_analysis, "get_vision_gateway", lambda: None)
    own = client.post(
        f"{BASE}/ppt/materials", headers=_hdr(accounts["a"]),
        data={"name": "待修正"},
        files={"file": ("own.png", _png_bytes(), "image/png")},
    )
    assert own.status_code == 200, own.text
    image_id = own.json()["id"]
    denied = client.patch(f"{BASE}/ppt/materials/{image_id}/caption",
                          headers=_hdr(accounts["b"]),
                          json={"caption": "错误说明"})
    assert denied.status_code == 404
    corrected = client.patch(f"{BASE}/ppt/materials/{image_id}/caption",
                             headers=_hdr(accounts["a"]),
                             json={"caption": "工作人员在室内讲解法律知识"})
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["caption"] == "工作人员在室内讲解法律知识"
    public = client.post(
        f"{BASE}/ppt/library/images", headers=_hdr(accounts["dev"]),
        data={"name": "活动图", "caption": "原说明", "category": "法治宣传",
              "source": "测试素材", "license_note": "测试环境内使用"},
        files={"file": ("public.png", _png_bytes(), "image/png")},
    )
    assert public.status_code == 200, public.text
    public_id = public.json()["id"]
    denied_public = client.patch(
        f"{BASE}/ppt/library/images/{public_id}/caption",
        headers=_hdr(accounts["a"]), json={"caption": "非法改动"})
    assert denied_public.status_code in (401, 403)
    updated_public = client.patch(
        f"{BASE}/ppt/library/images/{public_id}/caption",
        headers=_hdr(accounts["dev"]), json={"caption": "群众在室内参加普法活动"})
    assert updated_public.status_code == 200, updated_public.text


def test_outline_automatically_selects_owned_and_licensed_images(
        client, accounts, monkeypatch):
    from pptx import Presentation
    from app.application.ppt import image_analysis

    monkeypatch.setattr(image_analysis, "get_vision_gateway", lambda: None)
    own = client.post(
        f"{BASE}/ppt/materials", headers=_hdr(accounts["a"]),
        data={"name": "宪法宣誓", "caption": "工作人员进行宪法宣誓"},
        files={"file": ("own.png", _png_bytes(), "image/png")},
    )
    foreign = client.post(
        f"{BASE}/ppt/materials", headers=_hdr(accounts["b"]),
        data={"name": "他人私图", "caption": "宪法宣誓现场"},
        files={"file": ("foreign.png", _png_bytes(), "image/png")},
    )
    public = client.post(
        f"{BASE}/ppt/library/images", headers=_hdr(accounts["dev"]),
        data={"name": "普法照片", "caption": "群众参加普法活动",
              "category": "法治宣传", "source": "测试素材",
              "license_note": "测试环境内使用"},
        files={"file": ("public.png", _png_bytes(), "image/png")},
    )
    assert own.status_code == foreign.status_code == public.status_code == 200
    captured = {}

    def fake_generate(_assistant, _source_type, topic, _content, images,
                      *_args, **_kwargs):
        captured["ids"] = {item["id"] for item in images}
        return {"title": topic, "slides": [
            {"type": "content", "title": "宪法宣誓",
             "points": ["工作人员庄严宣誓"], "image_id": own.json()["id"]},
        ]}

    monkeypatch.setattr(ppt_engine, "generate_outline", fake_generate)
    monkeypatch.setattr(PPTService, "_audit_and_repair_outline",
                        lambda self, outline, *_args: outline)
    response = client.post(f"{BASE}/ppt/outline", headers=_hdr(accounts["a"]),
                           json={"topic": "法治宣传工作", "material_ids": []})
    assert response.status_code == 200, response.text
    assert own.json()["id"] in captured["ids"]
    assert public.json()["id"] in captured["ids"]
    assert foreign.json()["id"] not in captured["ids"]
    assert response.json()["outline"]["material_ids"] == [own.json()["id"]]
    assert response.json()["outline"]["image_selection_mode"] == "auto"
    draft = client.put(
        f"{BASE}/ppt/documents/{response.json()['doc_id']}/draft",
        headers=_hdr(accounts["a"]),
        json={"outline": {"title": response.json()["outline"]["title"],
                          "slides": response.json()["outline"]["slides"],
                          "image_selection_mode": "auto"}})
    assert draft.status_code == 200, draft.text
    generated = client.post(f"{BASE}/ppt/generate", headers=_hdr(accounts["a"]),
                            json={"doc_id": response.json()["doc_id"]})
    assert generated.status_code == 200, generated.text
    exported = client.get(
        f"{BASE}/ppt/documents/{response.json()['doc_id']}/download",
        headers=_hdr(accounts["a"]))
    assert exported.status_code == 200, exported.text
    deck = Presentation(io.BytesIO(exported.content))
    assert any("PICTURE" in str(shape.shape_type)
               for slide in deck.slides for shape in slide.shapes)
    disabled = client.post(f"{BASE}/ppt/outline", headers=_hdr(accounts["a"]),
                           json={"topic": "法治宣传工作", "material_ids": [],
                                 "auto_images": False})
    assert disabled.status_code == 200, disabled.text
    assert captured["ids"] == set()
    assert disabled.json()["outline"]["material_ids"] == []
    assert disabled.json()["outline"]["image_selection_mode"] == "off"


def test_saved_outline_without_material_ids_still_exports_library_image(
        client, accounts, monkeypatch):
    """客户端只回传 slides 时，文档级图片授权范围不能被清空。

    公共图库图片只能通过 material_ids 解析；一旦保存草稿把它丢掉，导出
    重新渲染时图片会静默消失，用户只会看到「图没了」。
    """
    from pptx import Presentation

    from app.application.ppt import image_analysis

    monkeypatch.setattr(image_analysis, "get_vision_gateway", lambda: None)
    public = client.post(
        f"{BASE}/ppt/library/images", headers=_hdr(accounts["dev"]),
        data={"name": "归档普法照", "caption": "工作人员向群众发放普法资料",
              "category": "法治宣传", "source": "测试素材",
              "license_note": "测试环境内使用"},
        files={"file": ("arch.png", _png_bytes((200, 120, 30)), "image/png")})
    assert public.status_code == 200, public.text
    pid = public.json()["id"]
    caption = public.json()["caption"]

    def fake_generate(_assistant, _source_type, topic, _content, images,
                      *_args, **_kwargs):
        assert any(item["id"] == pid for item in images)
        return {"title": topic, "slides": [
            {"type": "content", "title": caption,
             "points": ["工作人员向群众发放普法资料"], "image_id": pid},
        ]}

    monkeypatch.setattr(ppt_engine, "generate_outline", fake_generate)
    monkeypatch.setattr(PPTService, "_audit_and_repair_outline",
                        lambda self, outline, *_args: outline)
    made = client.post(f"{BASE}/ppt/outline", headers=_hdr(accounts["a"]),
                       json={"topic": "普法进社区", "material_ids": [pid]})
    assert made.status_code == 200, made.text
    doc_id = made.json()["doc_id"]
    outline = made.json()["outline"]

    # 第三方客户端只回传页面内容，不回传 material_ids
    saved = client.put(f"{BASE}/ppt/documents/{doc_id}/draft",
                       headers=_hdr(accounts["a"]),
                       json={"title": outline["title"],
                             "outline": {"title": outline["title"],
                                         "slides": outline["slides"]}})
    assert saved.status_code == 200, saved.text
    stored = client.get(f"{BASE}/ppt/documents/{doc_id}",
                        headers=_hdr(accounts["a"])).json()["outline"]
    assert stored["material_ids"] == [pid]

    exported = client.post(f"{BASE}/ppt/documents/{doc_id}/export",
                           headers=_hdr(accounts["a"]))
    assert exported.status_code == 200, exported.text
    deck = Presentation(io.BytesIO(exported.content))
    assert any("PICTURE" in str(shape.shape_type)
               for slide in deck.slides for shape in slide.shapes)


def test_model_cannot_attach_an_image_outside_candidate_ids():
    outline = {"slides": [{"type": "content", "title": "普法活动",
                           "image_id": "unauthorized", "points": ["开展普法"]}]}
    ppt_engine.resolve_slide_images(outline, [{"id": "allowed", "name": "普法活动",
                                               "caption": "群众参与普法活动"}])
    assert outline["slides"][0]["_image"] is None


def test_selected_template_defaults_to_adaptive_but_legacy_decks_keep_clone(monkeypatch):
    from app.application.ppt.service import PPTService

    assert not PPTService._strict_template_mode({"template_mode": "adaptive"})
    assert not PPTService._strict_template_mode({"template_mode": "designed"})
    assert PPTService._designed_template_mode({"template_mode": "designed"})
    assert PPTService._strict_template_mode({"template_mode": "strict"})
    assert PPTService._strict_template_mode({})

    calls = []
    monkeypatch.setattr(ppt_engine, "build_pptx_learned",
                        lambda *_a, **_k: calls.append("clone") or b"clone")
    monkeypatch.setattr(ppt_engine, "build_pptx",
                        lambda *_a, **_k: calls.append("adaptive" if _k.get("adaptive") else "plain") or b"adaptive")
    template = {"layout_library": [{"detected_type": "content"}]}
    assert ppt_engine.render_pptx({}, template, b"source", adaptive=True) == b"adaptive"
    assert calls == ["adaptive"]
    assert ppt_engine.render_pptx({}, template, b"source", adaptive=False) == b"clone"


def test_designed_template_uses_local_compiler_even_when_agent_url_is_set(monkeypatch):
    from app.application.ppt.service import PPTService
    from app.core.config import settings

    service = object.__new__(PPTService)
    calls = []
    monkeypatch.setattr(settings, "PPT_AGENT_URL", "http://unused-agent")
    monkeypatch.setattr(service, "_render_native_import", lambda *_: None)
    monkeypatch.setattr(service, "_ppt_assistant", lambda: object())
    monkeypatch.setattr(service, "_render_with_feedback", lambda outline, template,
                        **kwargs: (calls.append(kwargs) or b"designed", outline))
    outline = {"template_mode": "designed", "slides": []}
    data, renderer = service._render_pptx_bytes(
        object(), outline, {"colors": {}}, b"template")
    assert data == b"designed" and renderer == "local"
    assert calls[0]["base_pptx"] == b"template"
    assert calls[0]["adaptive"] is False


def test_designed_template_authors_pages_after_images_are_resolved(monkeypatch):
    from types import SimpleNamespace
    from app.application.ppt import page_authoring
    from app.application.ppt.service import PPTService

    service = object.__new__(PPTService)
    original = {"template_mode": "designed", "slides": [
        {"type": "content", "title": "工作安排", "points": ["组织学习"]}]}
    captured = []
    monkeypatch.setattr(service, "_render_native_import", lambda *_: None)
    monkeypatch.setattr(service, "_resolve_render_style", lambda *_: (
        {"colors": {}}, SimpleNamespace(id="tpl", builtin_id=None)))
    monkeypatch.setattr(service, "sanitize_outline", lambda outline, **_: outline)
    monkeypatch.setattr(service, "_user_images", lambda *_a, **_k: [])
    monkeypatch.setattr(service, "_ppt_assistant", lambda: "model")
    monkeypatch.setattr(service, "_tpl_base_bytes", lambda _row: b"template")
    monkeypatch.setattr(ppt_engine, "resolve_slide_images",
                        lambda outline, _images: (captured.append("images") or outline))
    monkeypatch.setattr(page_authoring, "author_pages",
                        lambda outline, _template, _assistant, _warnings, **_kwargs:
                        (captured.append("design") or outline))
    monkeypatch.setattr(service, "_render_with_feedback",
                        lambda outline, template, _warnings, **kwargs:
                        (captured.append(kwargs) or (b"pptx", outline)))
    data, _ = service.render_adaptive_pptx(
        SimpleNamespace(template_id="tpl", theme_id=""), original, "user")
    assert data == b"pptx"
    assert captured[:2] == ["images", "design"]
    assert captured[2]["base_pptx"] == b"template"
    assert captured[2]["adaptive"] is False
    captured.clear()
    monkeypatch.setattr(service, "_tpl_base_bytes", lambda _row: None)
    with pytest.raises(AppError, match="模板的源文件缺失"):
        service.render_adaptive_pptx(
            SimpleNamespace(template_id="tpl", theme_id=""), original, "user")
    assert captured == ["images"]


def test_designed_template_uses_original_page_preview(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.application.ppt.service import PPTService

    service = object.__new__(PPTService)
    monkeypatch.setattr(PPTService, "ppt_dir", property(lambda _self: tmp_path))
    folder = tmp_path / "tpl_prev" / "template-1"
    folder.mkdir(parents=True)
    (folder / "original.png").write_bytes(b"source-preview")
    (folder / "filled.png").write_bytes(b"filled-preview")
    template = {"layout_library": [{"detected_type": "content",
                                    "source_preview": "original.png",
                                    "preview": "filled.png"}]}
    assert service._design_reference_image(
        template, SimpleNamespace(id="template-1")) == b"source-preview"


def test_template_outline_defaults_to_designed_mode_when_not_specified(monkeypatch):
    from app.application.ppt.dto import OutlineIn
    from app.application.ppt.service import PPTService

    service = object.__new__(PPTService)
    captured = []
    monkeypatch.setattr(service, "_do_outline", lambda *_args, **kwargs:
                        (captured.append(kwargs) or {"ok": True}))
    body = OutlineIn(template_id="selected", topic="工作汇报")
    service.make_outline(body, object())
    assert captured[0]["template_mode"] == "designed"
    explicit = OutlineIn(template_id="selected", template_mode="strict", topic="工作汇报")
    service.make_outline(explicit, object())
    assert captured[1]["template_mode"] == "strict"


def test_selected_template_adaptive_mode_persists_through_generate(client, accounts):
    from pptx import Presentation
    import zipfile
    template = client.post(f"{BASE}/ppt/templates", headers=_hdr(accounts["a"]),
                           json={"name": "浅色汇报", "colors": {
                               "primary": "365472", "accent": "C99C4B"},
                                 "font": "微软雅黑"})
    assert template.status_code == 200, template.text
    doc_id = _blank_doc(client, accounts["a"], "版式选择")
    outline = {"title": "版式选择", "template_mode": "adaptive", "slides": [
        {"type": "content", "title": "工作进展", "points": ["依法履职", "服务群众"]}]}
    response = client.post(f"{BASE}/ppt/generate", headers=_hdr(accounts["a"]),
                           json={"doc_id": doc_id, "template_id": template.json()["id"],
                                 "outline": outline})
    assert response.status_code == 200, response.text
    saved = client.get(f"{BASE}/ppt/documents/{doc_id}",
                       headers=_hdr(accounts["a"])).json()
    assert saved["outline"]["template_mode"] == "adaptive"
    assert saved["template_id"] == template.json()["id"]
    deck = client.get(f"{BASE}/ppt/documents/{doc_id}/download",
                      headers=_hdr(accounts["a"]))
    assert deck.status_code == 200
    assert "工作进展" in " ".join(
        shape.text for slide in Presentation(io.BytesIO(deck.content)).slides
        for shape in slide.shapes if shape.has_text_frame)
    with zipfile.ZipFile(io.BytesIO(deck.content)) as package:
        first_xml = package.read("ppt/slides/slide1.xml")
    assert b"365472" in first_xml
    from app.core.fonts import DEFAULT_CJK_FONT
    assert DEFAULT_CJK_FONT.encode("utf-8") in first_xml
    assert "微软雅黑".encode("utf-8") not in first_xml

    recolored = {**outline, "color_override": True,
                 "color_theme_id": "gov_report_red"}
    regenerated = client.post(f"{BASE}/ppt/generate", headers=_hdr(accounts["a"]),
                              json={"doc_id": doc_id,
                                    "template_id": template.json()["id"],
                                    "outline": recolored})
    assert regenerated.status_code == 200, regenerated.text
    changed = client.get(f"{BASE}/ppt/documents/{doc_id}/download",
                         headers=_hdr(accounts["a"]))
    with zipfile.ZipFile(io.BytesIO(changed.content)) as package:
        second_xml = package.read("ppt/slides/slide1.xml")
    assert b"C00000" in second_xml
    assert b"365472" not in second_xml


def test_template_palette_changes_only_after_explicit_theme_choice(monkeypatch):
    from app.application.ppt.service import PPTService
    from app.core.fonts import DEFAULT_CJK_FONT

    service = object.__new__(PPTService)
    layouts = [{"id": "source-layout"}]
    source = {"colors": {"primary": "8E1B1B", "accent": "D6AA44"},
              "font": "微软雅黑", "layout_library": layouts}
    theme = ppt_engine.template_to_dict(ppt_engine.builtin_template("gov_report_blue"))
    monkeypatch.setattr(service, "_resolve_template",
                        lambda template_id, _fallback="":
                        (source if template_id else theme, None))
    implicit, _ = service._resolve_render_style(
        "selected", "gov_report_blue", {"template_mode": "adaptive"})
    assert implicit["colors"] == source["colors"]
    assert implicit["font"] == DEFAULT_CJK_FONT
    explicit, _ = service._resolve_render_style("selected", "gov_report_blue", {
        "template_mode": "adaptive", "color_override": True,
        "color_theme_id": "gov_report_blue"})
    assert explicit["colors"] == theme["colors"]
    assert explicit["layout_library"] is layouts
    strict, _ = service._resolve_render_style("selected", "gov_report_blue", {
        "template_mode": "strict", "color_override": True,
        "color_theme_id": "gov_report_blue"})
    assert strict["colors"] == source["colors"]
    assert strict["font"] == DEFAULT_CJK_FONT


def test_clearing_explicit_theme_restores_original_automatic_palette(monkeypatch):
    from app.application.ppt.service import PPTService

    service = object.__new__(PPTService)
    requested = []

    def resolve(_template_id, fallback=""):
        requested.append(fallback)
        return {"font": "微软雅黑", "colors": {"primary": fallback}}, None

    monkeypatch.setattr(service, "_resolve_template", resolve)
    original = {"template_mode": "adaptive", "base_theme_id": "gov_report_blue"}
    selected = {**original, "color_override": True,
                "color_theme_id": "gov_report_red"}
    service._resolve_render_style(None, "gov_report_red", selected)
    restored, _ = service._resolve_render_style(None, "gov_report_red", original)
    assert requested[0] == "gov_report_red"
    assert requested[-1] == "gov_report_blue"
    assert restored["colors"]["primary"] == "gov_report_blue"


def test_explicit_theme_choice_survives_outline_creation(client, accounts, fake_llm,
                                                         outline_payload):
    fake_llm._responder = lambda _messages: json.dumps(outline_payload, ensure_ascii=False)
    created = client.post(f"{BASE}/ppt/outline", headers=_hdr(accounts["a"]),
                          json={"source_type": "topic", "topic": "年度汇报",
                                "theme_id": "gov_report_blue", "color_override": True})
    assert created.status_code == 200, created.text
    outline = created.json()["outline"]
    assert outline["color_override"] is True
    assert outline["color_theme_id"] == "gov_report_blue"
    assert ppt_engine.builtin_template(outline["base_theme_id"])
    stored = client.get(f"{BASE}/ppt/documents/{created.json()['doc_id']}",
                        headers=_hdr(accounts["a"])).json()["outline"]
    assert stored["color_theme_id"] == "gov_report_blue"

    streamed = client.post(f"{BASE}/ppt/outline/stream", headers=_hdr(accounts["a"]),
                           json={"source_type": "topic", "topic": "年度汇报",
                                 "theme_id": "gov_report_blue", "color_override": True})
    assert streamed.status_code == 200, streamed.text
    events = _parse_sse(streamed.text)
    assert events[-1]["type"] == "done"
    assert events[-1]["data"]["outline"]["color_theme_id"] == "gov_report_blue"
    assert ppt_engine.builtin_template(events[-1]["data"]["outline"]["base_theme_id"])


def test_image_pages_choose_both_sides_without_losing_picture():
    slides = [{"type": "content", "title": "社区矫正", "points": ["依法监督"],
               "_image": {"id": str(i), "file_path": "photo.png"}}
              for i in range(2)]
    first = ppt_engine.choose_layout(slides[0])
    second = ppt_engine.choose_layout(slides[1], recent=[first], used={first: 1})
    assert {first, second} == {"content.image_right", "content.image_left"}


def test_adaptive_photo_layout_keeps_images_and_source_note(tmp_path):
    from PIL import Image
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    photo = tmp_path / "photo.png"
    Image.new("RGB", (200, 320), "#4488aa").save(photo)
    image = {"id": "photo", "name": "社区矫正", "caption": "活动现场",
             "file_path": str(photo), "credit": "本地图库",
             "license_note": "已授权使用"}
    outline = {"title": "司法工作", "slides": [
        {"type": "content", "title": f"工作{i}", "points": ["依法履职"],
         "_image": image} for i in range(2)]}
    theme = ppt_engine.template_to_dict(ppt_engine.builtin_template("gov_report_blue"))
    deck = Presentation(io.BytesIO(ppt_engine.render_pptx(outline, theme, adaptive=True)))
    positions = []
    for slide in deck.slides:
        pictures = [shape for shape in slide.shapes
                    if shape.shape_type == MSO_SHAPE_TYPE.PICTURE]
        assert len(pictures) == 1
        positions.append(pictures[0].left)
        assert "本地图库" in slide.notes_slide.notes_text_frame.text
        assert "已授权使用" in slide.notes_slide.notes_text_frame.text
    assert positions[0] != positions[1]


def test_outline_rejects_another_users_library_material(client, accounts, fake_llm):
    foreign = client.post(
        f"{BASE}/ppt/materials", headers=_hdr(accounts["b"]),
        data={"name": "他人图片", "caption": "不可访问"},
        files={"file": ("foreign.png", _png_bytes(), "image/png")},
    )
    assert foreign.status_code == 200
    response = client.post(f"{BASE}/ppt/outline", headers=_hdr(accounts["a"]), json={
        "topic": "工作汇报", "slide_count": 3,
        "material_ids": [foreign.json()["id"]],
    })
    assert response.status_code == 404


def test_upload_material_rejects_disguised_non_image(client, accounts):
    response = client.post(
        f"{BASE}/ppt/materials", headers=_hdr(accounts["a"]),
        data={"name": "伪装图片", "caption": ""},
        files={"file": ("fake.png", b"not-an-image", "image/png")},
    )
    assert response.status_code == 400


def test_analyze_materials_requires_login(client):
    r = client.post(f"{BASE}/ppt/materials/analyze")
    assert r.status_code in (401, 403), r.text


def test_analyze_materials_no_file_rejected(client, accounts):
    r = client.post(f"{BASE}/ppt/materials/analyze", headers=_hdr(accounts["a"]))
    assert r.status_code in (400, 422), r.text


def test_analyze_materials_returns_summary_and_text(client, accounts, fake_llm):
    """上传 txt：返回该份材料的 AI 摘要 + 提取文本，材料不再黑盒。

    v2 起材料分析升级为结构化输出（摘要 + 重点清单 + 数据表数量），
    这里喂合法 JSON 以验证解析链路真的生效，而不是只验证降级兜底。
    """
    fake_llm._responder = lambda m: json.dumps({
        "summary": "工作总结类文档，含一季度案件统计数据。",
        "key_points": ["一季度受理 120 件", "办结 115 件"],
        "tables": 1,
    }, ensure_ascii=False)
    body = "行政复议案件办理情况：一季度受理120件，办结115件。".encode("utf-8")
    r = client.post(
        f"{BASE}/ppt/materials/analyze",
        files=[("files", ("案件材料.txt", body, "text/plain"))],
        headers=_hdr(accounts["a"]))
    assert r.status_code == 200, r.text
    data = r.json()
    # 文案带聚合统计后缀，只校验份数部分
    assert data["message"].startswith("已分析 1 份材料")
    items = data["items"]
    assert len(items) == 1
    assert items[0]["filename"] == "案件材料.txt"
    assert items[0]["chars"] > 0
    assert "受理120件" in items[0]["text"]
    assert items[0]["summary"] == "工作总结类文档，含一季度案件统计数据。"
    # 结构化字段真的解析出来了（不是兜底空值）
    assert items[0]["key_points"] == ["一季度受理 120 件", "办结 115 件"]
    assert items[0]["tables"] == 1
    # 聚合统计与逐份结果一致
    assert data["totals"] == {"materials": 1, "key_points": 2, "tables": 1}
    # 摘要确实走了模型通道（否则这段逻辑等于没接）
    assert len(fake_llm.calls) == 1


def test_analyze_materials_degrades_on_non_json_summary(client, accounts, fake_llm):
    """模型返回非法 JSON（纯文本）时降级：摘要用原文，重点/表数留空，不抛异常。

    这条是兜底路径的护栏——结构化解析绝不能因为没有 JSON 就把整批材料分析打断。
    """
    fake_llm._responder = lambda m: "这不是 JSON，只是一段普通文本摘要"
    r = client.post(
        f"{BASE}/ppt/materials/analyze",
        files=[("files", ("材料.txt", "一季度受理120件".encode("utf-8"), "text/plain"))],
        headers=_hdr(accounts["a"]))
    assert r.status_code == 200, r.text
    item = r.json()["items"][0]
    assert item["summary"] == "这不是 JSON，只是一段普通文本摘要"
    assert item["key_points"] == []
    assert item["tables"] == 0
    # 聚合统计同步降级，不能 KeyError
    assert r.json()["totals"] == {"materials": 1, "key_points": 0, "tables": 0}


def test_analyze_materials_accepts_fenced_json(client, accounts, fake_llm):
    """模型用 ```json 代码围栏包裹、或前后带废话时，也要能解析出结构化字段。"""
    fenced = (
        "好的，分析结果如下：\n"
        "```json\n"
        '{"summary": "一季度案件办理情况表", "key_points": ["受理120件", "办结115件"],'
        ' "tables": 2}\n'
        "```\n"
    )
    fake_llm._responder = lambda m: fenced
    r = client.post(
        f"{BASE}/ppt/materials/analyze",
        files=[("files", ("案件.txt", "受理120件，办结115件".encode("utf-8"), "text/plain"))],
        headers=_hdr(accounts["a"]))
    assert r.status_code == 200, r.text
    item = r.json()["items"][0]
    assert item["summary"] == "一季度案件办理情况表"
    assert item["key_points"] == ["受理120件", "办结115件"]
    assert item["tables"] == 2


def test_analyze_materials_missing_fields_degrade(client, accounts, fake_llm):
    """JSON 里缺字段/类型不对时按类型兜底，不能抛异常或把脏值透给桌面端。"""
    fake_llm._responder = lambda m: json.dumps(
        {"summary": "只有摘要", "key_points": "not-a-list", "tables": "很多"},
        ensure_ascii=False)
    r = client.post(
        f"{BASE}/ppt/materials/analyze",
        files=[("files", ("残缺.txt", "一些内容".encode("utf-8"), "text/plain"))],
        headers=_hdr(accounts["a"]))
    assert r.status_code == 200, r.text
    item = r.json()["items"][0]
    assert item["summary"] == "只有摘要"
    # key_points 必须是数组：字符串按行拆成单条
    assert item["key_points"] == ["not-a-list"]
    # tables 必须是不小于 0 的整数：非数字降级为 0
    assert item["tables"] == 0


def test_analyze_materials_multi_format(client, accounts, fake_llm):
    """txt + csv + pptx 三种通道都能提取出内容。"""
    fake_llm._responder = lambda m: "（替身摘要）"
    pptx_bytes = _make_pptx_bytes([("旧汇报", ["受理120件", "办结115件"])])
    files = [
        ("files", ("概述.txt", "这是纯文本材料内容".encode("utf-8"), "text/plain")),
        ("files", ("数据表.csv", "指标,数值\n案件数,120\n".encode("utf-8"), "text/csv")),
        ("files", ("旧汇报.pptx", pptx_bytes,
                   "application/vnd.openxmlformats-officedocument.presentationml.presentation")),
    ]
    r = client.post(f"{BASE}/ppt/materials/analyze", files=files,
                    headers=_hdr(accounts["a"]))
    assert r.status_code == 200, r.text
    items = {i["filename"]: i for i in r.json()["items"]}
    assert set(items) == {"概述.txt", "数据表.csv", "旧汇报.pptx"}
    assert "这是纯文本材料内容" in items["概述.txt"]["text"]
    assert "案件数" in items["数据表.csv"]["text"] and "120" in items["数据表.csv"]["text"]
    assert "旧汇报" in items["旧汇报.pptx"]["text"]


def test_analyze_materials_unsupported_format_is_400(client, accounts, fake_llm):
    r = client.post(
        f"{BASE}/ppt/materials/analyze",
        files=[("files", ("乱码.bin", b"\x00\x01\x02binary", "application/octet-stream"))],
        headers=_hdr(accounts["a"]))
    assert r.status_code == 400, r.text
    assert "乱码.bin" in r.json()["detail"]


def test_analyze_materials_empty_file_is_400(client, accounts, fake_llm):
    r = client.post(
        f"{BASE}/ppt/materials/analyze",
        files=[("files", ("空文件.txt", b"", "text/plain"))],
        headers=_hdr(accounts["a"]))
    assert r.status_code == 400, r.text
    assert "没有可解析的材料" in r.json()["detail"]


def test_analyze_materials_caps_at_eight_files(client, accounts, fake_llm):
    """一次最多分析 8 份，超出的不处理（防止请求体无限膨胀）。"""
    fake_llm._responder = lambda m: "（替身摘要）"
    files = [("files", (f"材料{i}.txt", f"内容{i}".encode("utf-8"), "text/plain"))
             for i in range(9)]
    r = client.post(f"{BASE}/ppt/materials/analyze", files=files,
                    headers=_hdr(accounts["a"]))
    assert r.status_code == 200, r.text
    assert len(r.json()["items"]) == 8


# ============================================================ 2. documents/import


def test_import_pptx_requires_login(client):
    r = client.post(f"{BASE}/ppt/documents/import")
    assert r.status_code in (401, 403), r.text


def test_import_pptx_rejects_non_pptx(client, accounts):
    r = client.post(
        f"{BASE}/ppt/documents/import",
        files={"file": ("材料.docx", b"PK\x03\x04fake", "application/msword")},
        headers=_hdr(accounts["a"]))
    assert r.status_code == 400, r.text
    assert "仅支持 .pptx 文件" in r.json()["detail"]


def test_import_pptx_rejects_empty_file(client, accounts):
    r = client.post(
        f"{BASE}/ppt/documents/import",
        files={"file": ("空.pptx", b"",
                        "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        headers=_hdr(accounts["a"]))
    assert r.status_code == 400, r.text
    assert "文件内容为空" in r.json()["detail"]


def test_import_pptx_rejects_corrupt_zip(client, accounts):
    r = client.post(
        f"{BASE}/ppt/documents/import",
        files={"file": ("损坏.pptx", b"this-is-not-a-zip",
                        "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        headers=_hdr(accounts["a"]))
    assert r.status_code == 400, r.text
    assert "损坏" in r.json()["detail"]


def test_import_pptx_parses_editable_outline(client, accounts, fake_llm):
    """上传已有 pptx → 解析为可编辑大纲（不依赖 LLM）。"""
    data = _make_pptx_bytes([
        ("行政复议工作汇报", []),
        ("一季度案件办理情况", ["受理案件120件", "办结115件", "调解成功率86%"]),
    ])
    r = client.post(
        f"{BASE}/ppt/documents/import",
        files={"file": ("旧汇报.pptx", data,
                        "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        headers=_hdr(accounts["a"]))
    assert r.status_code == 200, r.text
    body = r.json()
    doc_id = body["doc_id"]
    assert doc_id
    assert "已导入" in body["message"]
    outline = body["outline"]
    slides = outline["slides"]
    # 成品导入保留原页面，不额外插入封面或结束页。
    assert len(slides) == 2
    assert outline["native_edit"] is True
    titles = " ".join(s["title"] for s in slides)
    assert "行政复议工作汇报" in titles
    assert "一季度案件办理情况" in titles
    # 正文要点被解析出来
    body_points = " ".join(
        p for s in slides for p in (s.get("points") or []))
    assert "受理案件120件" in body_points
    # 每页都有 sources 字段（可编辑大纲的 provenance 结构齐备）
    for s in slides:
        assert "sources" in s and isinstance(s["sources"], list)
    # 解析走的是规则通道，不调用模型
    assert len(fake_llm.calls) == 0

    # 导入结果已落库，可用同一编辑链路取回
    got = client.get(f"{BASE}/ppt/documents/{doc_id}", headers=_hdr(accounts["a"]))
    assert got.status_code == 200, got.text
    assert len(got.json()["outline"]["slides"]) == len(slides)

    outline["slides"][0]["title"] = "行政复议办理工作汇报"
    generated = client.post(f"{BASE}/ppt/generate", json={
        "doc_id": doc_id, "outline": outline}, headers=_hdr(accounts["a"]))
    assert generated.status_code == 200, generated.text
    exported = client.get(f"{BASE}/ppt/documents/{doc_id}/download", headers=_hdr(accounts["a"]))
    assert exported.status_code == 200
    import io
    import zipfile
    with zipfile.ZipFile(io.BytesIO(data)) as old, zipfile.ZipFile(io.BytesIO(exported.content)) as new:
        assert old.namelist() == new.namelist()
        changed = [name for name in old.namelist() if old.read(name) != new.read(name)]
        assert changed == ["ppt/slides/slide1.xml"]


def test_imported_pptx_appears_in_my_documents(client, accounts, fake_llm):
    data = _make_pptx_bytes([("清单页", ["要点一", "要点二"])])
    r = client.post(
        f"{BASE}/ppt/documents/import",
        files={"file": ("清单.pptx", data,
                        "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        headers=_hdr(accounts["a"]))
    doc_id = r.json()["doc_id"]
    lst = client.get(f"{BASE}/ppt/documents", headers=_hdr(accounts["a"])).json()
    assert any(d["id"] == doc_id for d in lst["items"])


# ============================================================ 3. outline/stream


def test_scene_wireframe_requires_document_owner(client, accounts, fake_llm, outline_payload):
    fake_llm._responder = lambda messages: json.dumps(outline_payload, ensure_ascii=False)
    created = client.post(f"{BASE}/ppt/outline", json={
        "source_type": "topic", "topic": "行政复议工作汇报", "auto_images": False},
        headers=_hdr(accounts["a"]))
    assert created.status_code == 200, created.text
    doc_id = created.json()["doc_id"]
    url = f"{BASE}/ppt/documents/{doc_id}/pages/2/scene.svg"
    response = client.get(url, headers=_hdr(accounts["a"]))
    assert response.status_code == 200, response.text
    assert "image/svg+xml" in response.headers["content-type"]
    assert "<svg" in response.text
    assert client.get(url).status_code == 401
    assert client.get(url, headers=_hdr(accounts["b"])).status_code in (403, 404)


def test_outline_stream_requires_login(client):
    r = client.post(f"{BASE}/ppt/outline/stream", json={"topic": "x"})
    assert r.status_code in (401, 403), r.text


@pytest.fixture
def outline_payload():
    """替身模型返回的大纲：含每页 sources 内容依据。"""
    return {
        "title": "行政复议工作汇报",
        "subtitle": "2026年第一季度",
        "slides": [
            {"type": "cover", "title": "行政复议工作汇报",
             "subtitle": "2026年第一季度", "sources": []},
            {"type": "content", "title": "案件办理情况",
             "points": ["受理案件120件", "办结115件"], "sources": ["材料A.txt"]},
            {"type": "closing", "title": "谢谢聆听，请批评指正", "sources": []},
        ],
    }


def test_outline_stream_event_sequence_and_done(client, accounts, fake_llm,
                                                outline_payload):
    """SSE：显式要求 8 页时，done 返回严格 8 页且保留来源标注。"""
    payload = {**outline_payload, "slides": [
        outline_payload["slides"][0], outline_payload["slides"][1],
        *[{"type": "content", "title": f"专题{i}", "points": [f"事项{i}"]}
          for i in range(2, 7)],
        outline_payload["slides"][-1],
    ]}
    fake_llm._responder = lambda m: json.dumps(payload, ensure_ascii=False)

    r = client.post(f"{BASE}/ppt/outline/stream", json={
        "source_type": "topic",
        "topic": "行政复议工作汇报",
        "slide_count": 8,
        "theme_id": "research_sand",
        "material_names": ["材料A.txt", "材料B.csv"],
        # 本测试聚焦 SSE 事件序列；自动配图会多一个图库挑选 stage，另测
        "auto_images": False,
    }, headers=_hdr(accounts["a"]))
    assert r.status_code == 200, r.text
    assert "text/event-stream" in r.headers["content-type"]

    events = _parse_sse(r.text)
    assert [e["type"] for e in events] == [
        "stage", "stage", "stage", "stage", "done"], events
    assert events[0]["text"] == "正在理解材料与任务要求…"
    assert events[1]["text"] == "正在梳理汇报结构…"
    assert events[2]["text"] == "正在自动检查页面结构与内容密度…"
    assert events[3]["text"] == "大纲已优化，正在保存…"

    done = events[4]
    assert done["data"]["doc_id"]
    document = client.get(
        f"{BASE}/ppt/documents/{done['data']['doc_id']}", headers=_hdr(accounts["a"]))
    assert document.status_code == 200, document.text
    assert document.json()["theme_id"] == "research_sand"
    assert document.json()["template_id"] is None
    outline = done["data"]["outline"]
    assert outline["title"] == "行政复议工作汇报"
    slides = outline["slides"]
    assert len(slides) == 8
    assert slides[0]["type"] == "cover"
    assert "points" not in slides[0] and "blocks" not in slides[0]
    assert slides[1]["type"] == "content"  # 自由生成不再强插目录
    original = next(s for s in slides if s["title"] == "案件办理情况")
    assert original["sources"] == ["材料A.txt"]
    assert slides[-1]["type"] == "closing"
    assert "points" not in slides[-1] and "blocks" not in slides[-1]
    assert all(s["title"] != "补充内容" for s in slides)

    # 来源标注要求确实下发给首次大纲模型；最后一次调用已是自动审查。
    prompts = [call["messages"][-1]["content"] for call in fake_llm.calls]
    assert any("【来源标注】" in p for p in prompts)
    assert any("材料A.txt" in p and "材料B.csv" in p for p in prompts)

    # 大纲已落库，后续编辑链路可拿到同一份
    got = client.get(f"{BASE}/ppt/documents/{done['data']['doc_id']}",
                     headers=_hdr(accounts["a"]))
    assert got.status_code == 200
    assert got.json()["outline"]["title"] == "行政复议工作汇报"


def test_outline_stream_auto_images_emits_gallery_stage(client, accounts,
                                                        fake_llm, outline_payload):
    """auto_images 默认开启且未勾选图片：事件序列多一个图库挑选 stage。"""
    fake_llm._responder = lambda m: json.dumps(outline_payload, ensure_ascii=False)
    r = client.post(f"{BASE}/ppt/outline/stream", json={
        "source_type": "topic", "topic": "随便一个主题",
    }, headers=_hdr(accounts["a"]))
    assert r.status_code == 200, r.text
    events = _parse_sse(r.text)
    assert events[-1]["type"] == "done", events
    texts = [e.get("text") for e in events if e["type"] == "stage"]
    assert "正在从图库挑选相关图片…" in texts, texts


def test_outline_stream_without_explicit_slide_count_keeps_model_page_count(
        client, accounts, fake_llm, outline_payload):
    """未填页数时服务端只给建议，不把模型的页面方案凑成六页。"""
    fake_llm._responder = lambda m: json.dumps(outline_payload, ensure_ascii=False)

    r = client.post(f"{BASE}/ppt/outline/stream", json={
        "source_type": "topic",
        "topic": "行政复议工作汇报",
        "material_names": ["材料A.txt"],
    }, headers=_hdr(accounts["a"]))
    assert r.status_code == 200, r.text

    events = _parse_sse(r.text)
    assert events[-1]["type"] == "done"
    slides = events[-1]["data"]["outline"]["slides"]
    assert len(slides) == len(outline_payload["slides"])
    assert slides[0]["type"] == "cover"
    assert slides[1]["type"] == "content"
    assert slides[-1]["type"] == "closing"
    assert any(s.get("sources") == ["材料A.txt"] for s in slides)


def test_outline_stream_emits_error_without_done(client, accounts, fake_llm):
    """模型返回非 JSON：只推 2 个 stage + error，不推 done。

    解析失败会自动重试一次（temperature 降到 0.2 并追加严格格式约束），
    因此模型共被调用 2 次；两次都失败才推 error，且绝不落库。
    """
    fake_llm._responder = lambda m: "抱歉，我无法完成这个请求。"
    r = client.post(f"{BASE}/ppt/outline/stream", json={
        "source_type": "topic", "topic": "随便一个主题", "auto_images": False,
    }, headers=_hdr(accounts["a"]))
    assert r.status_code == 200, r.text
    events = _parse_sse(r.text)
    assert [e["type"] for e in events] == ["stage", "stage", "error"], events
    assert events[-1]["message"]
    # 错误文案必须对用户可读：说明"没有生成任何文档"，且不带原始异常/英文报错
    message = events[-1]["message"]
    assert "没有生成任何文档" in message
    assert "Expecting" not in message and "JSONDecodeError" not in message
    # 首次失败 + 自动重试一次 = 2 次调用，重试温度降为 0.2
    assert len(fake_llm.calls) == 2, fake_llm.calls
    assert fake_llm.calls[0]["temperature"] == 0.5
    assert fake_llm.calls[1]["temperature"] == 0.2
    # 重试的 prompt 末尾追加了严格格式约束
    assert "只输出一个 JSON 对象" in fake_llm.calls[1]["messages"][-1]["content"]


def test_outline_stream_rescues_malformed_json_without_retry(client, accounts, fake_llm):
    """模型输出带尾随逗号 / 字符串内裸换行 / JSON 后追加说明：宽容解析直接救回。

    这是本次修复的核心场景：旧实现用贪婪正则 `\\{.*\\}` 吃到 JSON 后面的说明
    文字，再被零容错的 json.loads 抛成
    "Expecting property name enclosed in double quotes: ... (char 745)"。
    现在应当一次调用即成功，不产生额外重试开销。
    """
    malformed = (
        '{"title":"行政复议工作汇报","subtitle":"2026年第一季度","slides":['
        '{"type":"cover","title":"封面","subtitle":"副标题"},'
        '{"type":"content","title":"第一行\n第二行","points":["受理案件120件",],},'
        ']} 以上就是本次大纲，请查收。'
    )
    fake_llm._responder = lambda m: malformed
    r = client.post(f"{BASE}/ppt/outline/stream", json={
        "source_type": "topic", "topic": "随便一个主题", "auto_images": False,
    }, headers=_hdr(accounts["a"]))
    assert r.status_code == 200, r.text
    events = _parse_sse(r.text)
    assert [e["type"] for e in events] == [
        "stage", "stage", "stage", "stage", "done"], events
    # 首次大纲一次成功；第二次调用是服务端自动大纲审查，不是解析失败重试。
    assert len(fake_llm.calls) == 2, fake_llm.calls
    outline = events[-1]["data"]["outline"]
    titles = [s["title"] for s in outline["slides"]]
    assert titles[0] == "封面"
    assert "第一行\n第二行" in titles  # 字符串内裸换行被正确还原为换行


def test_outline_stream_slide_count_clamped(client, accounts, fake_llm,
                                            outline_payload):
    """slide_count 越界时按 6~18 夹紧后下发给模型。"""
    payload = {**outline_payload, "slides": [outline_payload["slides"][0]] + [
        {"type": "content", "title": f"专题{i}", "points": [f"事项{i}"]}
        for i in range(16)
    ] + [outline_payload["slides"][-1]]}
    fake_llm._responder = lambda m: json.dumps(payload, ensure_ascii=False)
    r = client.post(f"{BASE}/ppt/outline/stream", json={
        "source_type": "topic", "topic": "主题", "slide_count": 99,
    }, headers=_hdr(accounts["a"]))
    assert r.status_code == 200, r.text
    assert _parse_sse(r.text)[-1]["type"] == "done"
    prompts = [call["messages"][-1]["content"] for call in fake_llm.calls]
    assert any("18 页左右" in p or "18 页" in p for p in prompts)



def test_default_template_fallback_is_explicit_government_blue():
    """未选模板时必须显式回到 gov_report_blue，不能依赖模板数组顺序。"""
    class _Templates:
        def get(self, _template_id):
            return None

        def get_by_builtin_id(self, _builtin_id):
            return None

    svc = PPTService.__new__(PPTService)
    svc.templates = _Templates()
    template, row = svc._resolve_template(None, "")
    assert row is None
    assert template["name"] == "政务工作汇报（深蓝）"
    assert template["colors"]["primary"] == "17365D"


def test_server_auto_page_count_thresholds():
    assert PPTService._auto_slide_count("甲" * 999) == 6
    assert PPTService._auto_slide_count("甲" * 1000) == 10
    assert PPTService._auto_slide_count("甲" * 3000) == 10
    assert PPTService._auto_slide_count("甲" * 3001) == 15


def test_outline_sanitizer_cleans_cover_toc_and_closing_without_losing_body():
    outline = {
        "title": "社区矫正年度总结",
        "subtitle": "2026年",
        "slides": [
            {"type": "cover", "title": "社区矫正年度总结",
             "subtitle": "2026年", "points": ["汇报单位：白云区司法局", "不应保留"],
             "blocks": {"chart": {"x": 1}}},
            {"type": "content", "title": "年度概况", "points": ["要点A"],
             "sources": ["材料A"]},
            {"type": "content", "title": "重点工作", "points": ["要点B"]},
            {"type": "content", "title": "风险防控", "points": ["要点C"]},
            {"type": "content", "title": "下一步安排", "points": ["要点D"]},
            {"type": "closing", "title": "谢谢聆听", "points": ["不应保留"],
             "blocks": {"x": 1}},
        ],
    }
    out = PPTService.sanitize_outline(outline, target_count=6, ensure_toc=True)
    assert len(out["slides"]) == 6
    cover = out["slides"][0]
    assert cover["type"] == "cover"
    assert cover["unit"] == "白云区司法局"
    assert "points" not in cover and "blocks" not in cover
    assert out["slides"][1]["type"] == "toc"
    assert any(s["title"] == "年度概况" for s in out["slides"])
    closing = out["slides"][-1]
    assert closing["type"] == "closing"
    assert set(closing).issubset({"id", "type", "title"})


def test_ai_outline_adjust_endpoint_can_turn_toc_into_content(
        client, accounts, fake_llm):
    current = {
        "title": "汇报",
        "slides": [
            {"type": "cover", "title": "汇报"},
            {"type": "toc", "title": "目录", "points": ["一、概况"]},
            {"type": "closing", "title": "谢谢聆听"},
        ],
    }
    adjusted = {
        "title": "汇报",
        "slides": [
            {"type": "cover", "title": "汇报"},
            {"type": "content", "title": "工作概览", "points": ["一、概况"]},
            {"type": "closing", "title": "谢谢聆听"},
        ],
    }
    fake_llm._responder = lambda m: json.dumps(adjusted, ensure_ascii=False)
    r = client.post(
        f"{BASE}/ppt/ai/outline-adjust",
        json={"instruction": "把目录页改成正文页", "outline": current},
        headers=_hdr(accounts["a"]),
    )
    assert r.status_code == 200, r.text
    out = r.json()["outline"]
    assert out["slides"][1]["type"] == "content"
    assert out["slides"][1]["title"] == "工作概览"


# ============================================================ 4. ai/slide-action


def test_ai_slide_action_requires_login(client):
    r = client.post(f"{BASE}/ppt/ai/slide-action",
                    json={"action": "rewrite", "slide": {"title": "x"}})
    assert r.status_code in (401, 403), r.text


def test_ai_slide_action_requires_action_and_slide(client, accounts):
    r1 = client.post(f"{BASE}/ppt/ai/slide-action", json={"slide": {"title": "x"}},
                     headers=_hdr(accounts["a"]))
    r2 = client.post(f"{BASE}/ppt/ai/slide-action", json={"action": "rewrite"},
                     headers=_hdr(accounts["a"]))
    assert r1.status_code == 422, r1.text
    assert r2.status_code == 422, r2.text


# ✅ 已修复（BUG-1）: server/app/application/ppt/ppt_engine.py:797
#   原写法 normalize_outline({"slides": [merged]})["slides"][0] 按索引取首屏。
#   normalize_outline() 恒定保证"首屏是 cover、末屏是 closing"，对非 cover 页
#   （编辑器里最常见的正文页）会在 index 0 插入一页合成封面，导致取到
#   title="演示文稿" 的空封面、AI 改写结果被整体丢弃。
#   现改为按 id 取回真正被改写的那一页，并保留 normalize_outline 的字段规范化。
#   下面两条即该缺陷的回归用例（原为 xfail(strict=True)，修复后转为常规断言）。


def test_ai_slide_action_rewrite_keeps_id_and_sources(client, accounts, fake_llm):
    slide = {"id": "abc12345", "type": "content", "title": "案件办理",
             "points": ["原要点"], "blocks": {}, "sources": ["材料A.txt"]}
    fake_llm._responder = lambda m: json.dumps({
        "id": "abc12345", "type": "content", "title": "一季度案件办理情况",
        "points": ["受理案件120件", "办结115件"], "blocks": {},
        "sources": ["材料A.txt"]}, ensure_ascii=False)

    r = client.post(f"{BASE}/ppt/ai/slide-action",
                    json={"action": "rewrite", "slide": slide},
                    headers=_hdr(accounts["a"]))
    assert r.status_code == 200, r.text
    out = r.json()["slide"]
    assert out["id"] == "abc12345", "单页改写必须保留原 id，否则编辑器选中态丢失"
    assert out["title"] == "一季度案件办理情况"
    assert len(out["points"]) == 2
    assert "sources" in out
    assert "整体重写这一页" in fake_llm.last_prompt


def test_ai_slide_action_custom_passes_instruction(client, accounts, fake_llm):
    slide = {"id": "s1", "type": "content", "title": "标题", "points": ["要点"]}
    fake_llm._responder = lambda m: json.dumps(
        {**slide, "title": "更正式的标题"}, ensure_ascii=False)
    r = client.post(f"{BASE}/ppt/ai/slide-action",
                    json={"action": "custom", "slide": slide,
                          "instruction": "把语气改得更正式一些"},
                    headers=_hdr(accounts["a"]))
    assert r.status_code == 200, r.text
    assert r.json()["slide"]["title"] == "更正式的标题"
    assert "把语气改得更正式一些" in fake_llm.last_prompt


def test_ai_slide_action_cover_page_roundtrip(client, accounts, fake_llm):
    """封面页（norm[0].type == cover）不会被插入合成封面，改写结果能正确返回。

    BUG-1 修复前这条也通过，正是它把缺陷范围锁定在「非 cover 页」。
    """
    slide = {"id": "cover1", "type": "cover", "title": "旧封面",
             "subtitle": "旧副标题", "points": [], "sources": []}
    fake_llm._responder = lambda m: json.dumps(
        {**slide, "title": "行政复议工作汇报", "subtitle": "2026年第一季度"},
        ensure_ascii=False)
    r = client.post(f"{BASE}/ppt/ai/slide-action",
                    json={"action": "rewrite", "slide": slide},
                    headers=_hdr(accounts["a"]))
    assert r.status_code == 200, r.text
    out = r.json()["slide"]
    assert out["id"] == "cover1"
    assert out["title"] == "行政复议工作汇报"
    assert out["subtitle"] == "2026年第一季度"


def test_ai_slide_action_content_page_returns_ai_result(fake_llm):
    """BUG-1 最小复现（直接打桩 ppt_engine.ai_slide_action，不经 HTTP）。

    防回归要点：正文页（type=content）经 normalize_outline 后会在 index 0 被
    插入一页合成封面（title="演示文稿"）。若哪天又把实现改回按索引取
    ["slides"][0]，本用例会立刻失败。
    """
    from app.application.ppt import ppt_engine

    slide = {"id": "abc12345", "type": "content", "title": "原标题",
             "points": ["原要点"], "sources": ["材料A.txt"]}
    fake_llm._responder = lambda m: json.dumps({
        "id": "abc12345", "type": "content", "title": "AI改写后的标题",
        "points": ["改写要点一", "改写要点二"], "sources": ["材料A.txt"],
    }, ensure_ascii=False)

    out = ppt_engine.ai_slide_action(fake_llm, "rewrite", slide)

    # 1) 必须是被改写的那一页，不能是 normalize_outline 凭空造的封面/结束页
    assert out["id"] == "abc12345", "正文页改写必须保留原 id"
    assert out["type"] == "content", f"不应返回合成页，实际 type={out['type']}"
    # 2) 内容必须是 AI 的输出，不能被丢弃成空壳
    assert out["title"] == "AI改写后的标题", f"实际 title={out['title']!r}"
    assert out["points"] == ["改写要点一", "改写要点二"], f"实际 points={out['points']!r}"
    assert out["sources"] == ["材料A.txt"], f"实际 sources={out['sources']!r}"
    # 3) 只返回一页的字段，不应混入 closing 页的标题
    assert out["title"] != "谢谢聆听，请批评指正"
    assert out["title"] != "演示文稿"


def test_ai_slide_action_model_garbage_is_502(client, accounts, fake_llm):
    fake_llm._responder = lambda m: "我无法输出 JSON"
    r = client.post(f"{BASE}/ppt/ai/slide-action",
                    json={"action": "rewrite", "slide": {"id": "s", "title": "x"}},
                    headers=_hdr(accounts["a"]))
    assert r.status_code == 502, r.text
    assert r.json()["detail"]


# ============================================================ 5. ai/visual


def test_ai_visual_requires_login(client):
    r = client.post(f"{BASE}/ppt/ai/visual",
                    json={"kind": "chart", "slide": {"title": "x"}})
    assert r.status_code in (401, 403), r.text


def test_ai_visual_requires_kind_and_slide(client, accounts):
    r1 = client.post(f"{BASE}/ppt/ai/visual", json={"slide": {"title": "x"}},
                     headers=_hdr(accounts["a"]))
    r2 = client.post(f"{BASE}/ppt/ai/visual", json={"kind": "chart"},
                     headers=_hdr(accounts["a"]))
    assert r1.status_code == 422, r1.text
    assert r2.status_code == 422, r2.text


def test_ai_visual_chart_writes_blocks(client, accounts, fake_llm):
    slide = {"id": "s1", "type": "content", "title": "案件数据",
             "points": ["受理120件", "办结115件"]}
    fake_llm._responder = lambda m: json.dumps({"blocks": {"chart": {
        "chart_type": "bar",
        "categories": ["受理", "办结"],
        "series": [{"name": "案件数", "values": [120, 115]}]}}}, ensure_ascii=False)
    r = client.post(f"{BASE}/ppt/ai/visual", json={"kind": "chart", "slide": slide},
                    headers=_hdr(accounts["a"]))
    assert r.status_code == 200, r.text
    out = r.json()["slide"]
    assert out["type"] == "chart"
    assert out["blocks"]["chart"]["chart_type"] == "bar"
    assert out["blocks"]["chart"]["series"][0]["values"] == [120, 115]


def test_ai_process_routes_to_drawio_when_configured(client, accounts, fake_llm, monkeypatch):
    from app.application.ppt.drawio_service import DrawioService
    monkeypatch.setattr("app.core.config.settings.DRAWIO_MCP_URL", "http://drawio-mcp:3001")
    monkeypatch.setattr(DrawioService, "get_reference", lambda _self: "mxGraphModel reference")
    xml = ('<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
           '<mxCell id="n1" value="受理" vertex="1" parent="1">'
           '<mxGeometry x="0" y="0" width="160" height="80" as="geometry"/>'
           '</mxCell></root></mxGraphModel>')
    fake_llm._responder = lambda _messages: json.dumps({"xml": xml}, ensure_ascii=False)
    response = client.post(f"{BASE}/ppt/ai/visual", json={
        "kind": "process", "slide": {"id": "s1", "title": "办理流程", "points": ["受理"]},
    }, headers=_hdr(accounts["a"]))
    assert response.status_code == 200, response.text
    from app.application.ppt.drawio_native import parse_diagram
    nodes = parse_diagram(response.json()["slide"]["blocks"]["drawio_xml"])["nodes"]
    assert [node["label"] for node in nodes] == ["受理"]
    assert nodes[0]["style"]["shadow"] == "1"
    assert "mxGraphModel reference" in fake_llm.last_prompt


def test_ai_relationship_routes_to_drawio_with_selected_template(client, accounts, fake_llm, monkeypatch):
    from app.application.ppt.drawio_service import DrawioService
    monkeypatch.setattr("app.core.config.settings.DRAWIO_MCP_URL", "http://drawio-mcp:3001")
    monkeypatch.setattr(DrawioService, "get_reference", lambda _self: "mxGraphModel reference")
    template = client.post(f"{BASE}/ppt/templates", json={
        "name": "关系图风格", "colors": {"primary": "123456", "accent": "ABCDEF"},
        "font": "思源黑体",
    }, headers=_hdr(accounts["a"]))
    assert template.status_code in (200, 201), template.text
    xml = ('<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
           '<mxCell id="n1" value="司法局" vertex="1" parent="1">'
           '<mxGeometry x="0" y="0" width="160" height="80" as="geometry"/>'
           '</mxCell></root></mxGraphModel>')
    fake_llm._responder = lambda _messages: json.dumps({"xml": xml}, ensure_ascii=False)
    response = client.post(f"{BASE}/ppt/ai/visual", json={
        "kind": "relationship", "slide": {"id": "s1", "title": "单位关系"},
        "template_id": template.json()["id"],
    }, headers=_hdr(accounts["a"]))
    assert response.status_code == 200, response.text
    assert response.json()["slide"]["blocks"]["drawio_kind"] == "relationship"
    assert "#123456" in fake_llm.last_prompt

    forbidden = client.post(f"{BASE}/ppt/ai/visual", json={
        "kind": "relationship", "slide": {"id": "s2", "title": "其他单位关系"},
        "template_id": template.json()["id"],
    }, headers=_hdr(accounts["b"]))
    # 他人私有模板按「不存在」处理（与模板详情/收藏的 404 语义一致，不泄露存在性）
    assert forbidden.status_code == 404


def test_drawio_source_download_is_owned_and_multi_page(client, accounts):
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    from test_drawio_mcp import NATIVE_XML
    created = client.post(f"{BASE}/ppt/blank", json={"title": "图示文稿"},
                          headers=_hdr(accounts["a"]))
    assert created.status_code in (200, 201), created.text
    doc_id = created.json()["doc_id"]
    outline = {"title": "图示文稿", "slides": [
        {"type": "cover", "title": "图示文稿"},
        {"type": "process", "title": "办理流程", "blocks": {"drawio_xml": NATIVE_XML}},
        {"type": "process", "title": "复核流程", "blocks": {"drawio_xml": NATIVE_XML}},
        {"type": "closing", "title": "谢谢"},
    ]}
    saved = client.put(f"{BASE}/ppt/documents/{doc_id}/draft", json={"outline": outline},
                       headers=_hdr(accounts["a"]))
    assert saved.status_code == 200, saved.text
    denied = client.get(f"{BASE}/ppt/documents/{doc_id}/drawio", headers=_hdr(accounts["b"]))
    assert denied.status_code in (403, 404)
    downloaded = client.get(f"{BASE}/ppt/documents/{doc_id}/drawio", headers=_hdr(accounts["a"]))
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.content.count(b"<diagram ") == 2
    assert b"<mxGraphModel" in downloaded.content
    exported = client.post(f"{BASE}/ppt/documents/{doc_id}/export",
                           headers=_hdr(accounts["a"]))
    assert exported.status_code == 200, exported.text
    presentation = Presentation(io.BytesIO(exported.content))
    assert len(presentation.slides) == 4
    for slide in (presentation.slides[1], presentation.slides[2]):
        assert {"受理", "审核"} <= {
            shape.text for shape in slide.shapes if shape.has_text_frame
        }
        assert any(shape.shape_type == MSO_SHAPE_TYPE.LINE for shape in slide.shapes)


def test_drawio_source_download_requires_a_diagram(client, accounts):
    created = client.post(f"{BASE}/ppt/blank", json={"title": "普通文稿"},
                          headers=_hdr(accounts["a"]))
    doc_id = created.json()["doc_id"]
    response = client.get(f"{BASE}/ppt/documents/{doc_id}/drawio",
                          headers=_hdr(accounts["a"]))
    assert response.status_code == 400


def test_ai_process_falls_back_when_drawio_is_unavailable(client, accounts, fake_llm, monkeypatch):
    from app.application.ppt.drawio_service import DrawioService
    monkeypatch.setattr("app.core.config.settings.DRAWIO_MCP_URL", "http://drawio-mcp:3001")
    monkeypatch.setattr(DrawioService, "get_reference", lambda _self: None)
    fake_llm._responder = lambda _messages: json.dumps({
        "blocks": {"process": ["受理", "审核", "办结"]},
    }, ensure_ascii=False)
    response = client.post(f"{BASE}/ppt/ai/visual", json={
        "kind": "process", "slide": {
            "id": "s1", "title": "办理流程", "points": ["受理、审核、办结"],
            "blocks": {"drawio_xml": "old diagram"},
        },
    }, headers=_hdr(accounts["a"]))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["slide"]["id"] == "s1"
    assert result["slide"]["blocks"] == {"process": ["受理", "审核", "办结"]}
    assert result["warnings"] == ["图示增强服务暂不可用，已自动使用本地流程图生成。"]
    assert len(fake_llm.calls) == 1


def test_ai_relationship_fallback_explains_loss_of_connections(client, accounts, fake_llm, monkeypatch):
    from app.application.ppt.drawio_service import DrawioService
    monkeypatch.setattr("app.core.config.settings.DRAWIO_MCP_URL", "http://drawio-mcp:3001")
    monkeypatch.setattr(DrawioService, "get_reference", lambda _self: None)
    fake_llm._responder = lambda _messages: json.dumps({
        "blocks": {"process": ["司法局", "业务科室", "基层单位"]},
    }, ensure_ascii=False)
    response = client.post(f"{BASE}/ppt/ai/visual", json={
        "kind": "relationship", "slide": {"id": "s1", "title": "单位关系"},
    }, headers=_hdr(accounts["a"]))
    assert response.status_code == 200, response.text
    assert "连线关系" in response.json()["warnings"][0]


def test_ai_process_invalid_drawio_output_does_not_trigger_fallback(client, accounts, fake_llm, monkeypatch):
    from app.application.ppt.drawio_service import DrawioService
    monkeypatch.setattr("app.core.config.settings.DRAWIO_MCP_URL", "http://drawio-mcp:3001")
    monkeypatch.setattr(DrawioService, "get_reference", lambda _self: "mxGraphModel reference")
    fake_llm._responder = lambda _messages: json.dumps({"xml": "invalid XML"})
    response = client.post(f"{BASE}/ppt/ai/visual", json={
        "kind": "process", "slide": {"id": "s1", "title": "办理流程", "points": ["受理"]},
    }, headers=_hdr(accounts["a"]))
    assert response.status_code == 502, response.text
    assert "结构检查" in response.json()["detail"]
    assert len(fake_llm.calls) == 1


def test_ai_visual_timeline_sets_type(client, accounts, fake_llm):
    slide = {"id": "s1", "type": "content", "title": "工作进程"}
    fake_llm._responder = lambda m: json.dumps({"blocks": {"timeline": [
        {"time": "1月", "text": "部署动员"}, {"time": "3月", "text": "阶段总结"}]}},
        ensure_ascii=False)
    r = client.post(f"{BASE}/ppt/ai/visual", json={"kind": "timeline", "slide": slide},
                    headers=_hdr(accounts["a"]))
    assert r.status_code == 200, r.text
    out = r.json()["slide"]
    assert out["type"] == "timeline"
    assert len(out["blocks"]["timeline"]) == 2


def test_ai_visual_error_payload_is_502(client, accounts, fake_llm):
    fake_llm._responder = lambda m: json.dumps({"error": "数据不足，无法生成图表"},
                                               ensure_ascii=False)
    r = client.post(f"{BASE}/ppt/ai/visual",
                    json={"kind": "chart", "slide": {"id": "s", "title": "x"}},
                    headers=_hdr(accounts["a"]))
    assert r.status_code == 502, r.text
    assert "数据不足" in r.json()["detail"]


# ============================================================ 6. ai/structure


def test_ai_structure_requires_login(client):
    r = client.post(f"{BASE}/ppt/ai/structure",
                    json={"action": "add", "slides": [], "index": 0})
    assert r.status_code in (401, 403), r.text


def test_ai_structure_requires_fields(client, accounts):
    r = client.post(f"{BASE}/ppt/ai/structure", json={"action": "add"},
                    headers=_hdr(accounts["a"]))
    assert r.status_code == 422, r.text


def _three_slides():
    return [
        {"id": "c1", "type": "cover", "title": "封面", "subtitle": "副标题",
         "points": [], "sources": []},
        {"id": "n1", "type": "content", "title": "正文页",
         "points": ["要点一", "要点二", "要点三", "要点四"], "sources": ["材料A.txt"]},
        {"id": "e1", "type": "closing", "title": "谢谢聆听，请批评指正",
         "points": [], "sources": []},
    ]


def test_ai_structure_add_inserts_after_index(client, accounts, fake_llm):
    fake_llm._responder = lambda m: json.dumps(
        {"type": "content", "title": "新增的一页", "points": ["新增要点"]},
        ensure_ascii=False)
    slides = _three_slides()
    r = client.post(f"{BASE}/ppt/ai/structure",
                    json={"action": "add", "slides": slides, "index": 1},
                    headers=_hdr(accounts["a"]))
    assert r.status_code == 200, r.text
    out = r.json()["slides"]
    assert len(out) == 4
    assert out[2]["title"] == "新增的一页"
    # 新页被 normalize 补齐完整结构
    assert "sources" in out[2] and "id" in out[2]
    assert len(fake_llm.calls) == 1


def test_ai_structure_split_is_deterministic_without_llm(client, accounts, fake_llm):
    """拆分是纯规则逻辑：不调用模型，要点对半分，续页标题带（续）。"""
    slides = _three_slides()
    r = client.post(f"{BASE}/ppt/ai/structure",
                    json={"action": "split", "slides": slides, "index": 1},
                    headers=_hdr(accounts["a"]))
    assert r.status_code == 200, r.text
    out = r.json()["slides"]
    assert len(out) == 4
    assert out[1]["points"] == ["要点一", "要点二"]
    assert out[2]["points"] == ["要点三", "要点四"]
    assert out[2]["title"].endswith("（续）")
    assert len(fake_llm.calls) == 0, "拆分不应调用模型"


def test_ai_structure_merge_combines_points(client, accounts, fake_llm):
    slides = [
        {"id": "c1", "type": "cover", "title": "封面", "points": []},
        {"id": "n1", "type": "content", "title": "页一", "points": ["A", "B"]},
        {"id": "n2", "type": "content", "title": "页二", "points": ["C"]},
        {"id": "e1", "type": "closing", "title": "谢谢聆听，请批评指正", "points": []},
    ]
    r = client.post(f"{BASE}/ppt/ai/structure",
                    json={"action": "merge", "slides": slides, "index": 1},
                    headers=_hdr(accounts["a"]))
    assert r.status_code == 200, r.text
    out = r.json()["slides"]
    assert len(out) == 3
    assert out[1]["points"] == ["A", "B", "C"]
    assert len(fake_llm.calls) == 0, "合并不应调用模型"


def test_ai_structure_out_of_range_index_is_502(client, accounts, fake_llm):
    slides = _three_slides()
    r = client.post(f"{BASE}/ppt/ai/structure",
                    json={"action": "split", "slides": slides, "index": 99},
                    headers=_hdr(accounts["a"]))
    assert r.status_code == 502, r.text
    assert r.json()["detail"]


def test_ai_structure_merge_last_page_is_502(client, accounts, fake_llm):
    slides = _three_slides()
    r = client.post(f"{BASE}/ppt/ai/structure",
                    json={"action": "merge", "slides": slides, "index": 2},
                    headers=_hdr(accounts["a"]))
    assert r.status_code == 502, r.text


def test_ai_structure_unknown_action_is_502(client, accounts, fake_llm):
    r = client.post(f"{BASE}/ppt/ai/structure",
                    json={"action": "teleport", "slides": _three_slides(), "index": 0},
                    headers=_hdr(accounts["a"]))
    assert r.status_code == 502, r.text


# ============================================================ 7. 越权与资源隔离


def test_other_users_document_is_404_not_403(client, accounts):
    """他人的 PPT 文档一律 404（不泄露存在性），而不是 403。"""
    my_doc = _blank_doc(client, accounts["a"], "A的私有PPT")

    got = client.get(f"{BASE}/ppt/documents/{my_doc}", headers=_hdr(accounts["b"]))
    assert got.status_code == 404, got.text

    patch = client.patch(f"{BASE}/ppt/documents/{my_doc}", json={"title": "被改了"},
                         headers=_hdr(accounts["b"]))
    assert patch.status_code == 404, patch.text

    dele = client.delete(f"{BASE}/ppt/documents/{my_doc}", headers=_hdr(accounts["b"]))
    assert dele.status_code == 404, dele.text

    # 本人的仍然正常
    ok = client.get(f"{BASE}/ppt/documents/{my_doc}", headers=_hdr(accounts["a"]))
    assert ok.status_code == 200


def test_document_list_is_per_user(client, accounts):
    my_doc = _blank_doc(client, accounts["a"], "仅A可见")
    lst_b = client.get(f"{BASE}/ppt/documents", headers=_hdr(accounts["b"])).json()
    assert all(d["id"] != my_doc for d in lst_b["items"])


def test_missing_document_is_404(client, accounts):
    r = client.get(f"{BASE}/ppt/documents/no-such-doc-id", headers=_hdr(accounts["a"]))
    assert r.status_code == 404


def test_download_before_generate_is_404(client, accounts):
    doc_id = _blank_doc(client, accounts["a"], "尚未生成")
    r = client.get(f"{BASE}/ppt/documents/{doc_id}/download",
                   headers=_hdr(accounts["a"]))
    assert r.status_code == 404, r.text


# ============================================================ 页数硬约束回归


def test_outline_page_count_hard_constraint_two_pages():
    """2 页请求必须严格得到 2 页，且规范化不得因为补 cover/closing 膨胀页数。"""
    from app.application.ppt import ppt_engine

    raw = {
        "title": "两页汇报",
        "subtitle": "",
        "slides": [
            {"type": "cover", "title": "两页汇报"},
            {"type": "content", "title": "模型多生成的正文", "points": ["事实内容"]},
            {"type": "closing", "title": "谢谢聆听"},
        ],
    }
    out = ppt_engine.normalize_outline(raw, target_count=2)
    assert len(out["slides"]) == 2
    assert out["slides"][0]["type"] == "cover"
    assert out["slides"][-1]["type"] == "closing"


def test_outline_page_count_hard_constraint_does_not_fabricate_fillers():
    """模型少页时允许补位，但补位必须显式标记待补充，不能制造事实/数据。"""
    from app.application.ppt import ppt_engine

    raw = {
        "title": "四页汇报",
        "slides": [
            {"type": "cover", "title": "四页汇报"},
            {"type": "closing", "title": "谢谢聆听"},
        ],
    }
    out = ppt_engine.normalize_outline(raw, target_count=4)
    assert len(out["slides"]) == 4
    fillers = out["slides"][1:-1]
    assert all(s["title"] == "补充内容" for s in fillers)
    assert all("待根据已确认材料补充" in " ".join(s["points"]) for s in fillers)


def test_learned_layout_explicit_binding_overrides_auto_match():
    """模板骨架编辑器显式绑定 L2 后，必须优先使用 L2 而不是自动挑同类型第一张。"""
    from app.application.ppt import ppt_engine

    layouts = [
        {"id": "L0", "detected_type": "content", "name": "正文A"},
        {"id": "L2", "detected_type": "cover", "name": "用户指定骨架"},
    ]
    picked = ppt_engine._pick_layout(
        layouts, "content", used={}, preferred_layout_id="L2")
    assert picked["id"] == "L2"

    auto = ppt_engine._pick_layout(
        layouts, "content", used={}, preferred_layout_id="")
    assert auto["id"] == "L0"


def test_template_import_requires_a_fillable_content_page():
    from app.application.ppt import ppt_engine
    import pytest

    with pytest.raises(ValueError, match="标题和正文文本框"):
        ppt_engine.validate_learned_template({"slide_size": {"w": 13.333, "h": 7.5}, "layouts": [{
            "element_schema": [{"kind": "text", "role": "content"},
                               {"kind": "picture", "role": "fixed"}]}]})


def test_every_builtin_template_exports_core_page_types():
    from io import BytesIO
    from pptx import Presentation
    from app.application.ppt import ppt_engine

    outline = {"slides": [
        {"type": "cover", "title": "测试封面"},
        {"type": "content", "title": "工作重点", "points": ["第一项", "第二项"]},
        {"type": "process", "title": "办理流程",
         "blocks": {"process": ["受理", "审核", "办结"]}},
    ]}
    for spec in ppt_engine.BUILTIN_TEMPLATES:
        data = ppt_engine.render_pptx(outline, ppt_engine.template_to_dict(spec))
        slides = Presentation(BytesIO(data)).slides
        assert len(slides) == 3, spec["id"]
        text = "\n".join(shape.text for slide in slides for shape in slide.shapes
                         if shape.has_text_frame)
        assert all(word in text for word in ("工作重点", "第一项", "受理", "办结")), spec["id"]
    fingerprints = {
        tuple(ppt_engine.template_to_dict(spec)["layouts"][page]
              for page in ("cover", "section", "content", "summary"))
        for spec in ppt_engine.BUILTIN_TEMPLATES
    }
    assert len(fingerprints) == len(ppt_engine.BUILTIN_TEMPLATES)


def test_official_template_uses_current_builtin_rules_after_code_update():
    from types import SimpleNamespace
    stale = SimpleNamespace(
        id="row-1", is_official=True, builtin_id="policy_blue",
        name="旧名称", colors={"primary": "000000"},
        layouts={"content": "bar_title"}, font="旧字体")
    design = ppt_engine.template_to_dict(stale)
    assert design["id"] == "row-1"
    assert design["colors"]["primary"] == "1F4E9C"
    assert design["layouts"]["content"] == "content.compare"


def test_learned_template_overflow_keeps_all_points():
    from io import BytesIO
    from pptx import Presentation
    from pptx.util import Inches
    from app.application.ppt import ppt_engine

    source = Presentation()
    page = source.slides.add_slide(source.slide_layouts[6])
    page.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(1)).text = "示例标题"
    page.shapes.add_textbox(Inches(1), Inches(2), Inches(6), Inches(3)).text = "示例正文"
    buf = BytesIO()
    source.save(buf)
    learned = ppt_engine.analyze_template(buf.getvalue())
    template = {**ppt_engine.template_to_dict(ppt_engine.BUILTIN_TEMPLATES[0]),
                "layout_library": learned["layouts"]}
    warnings = []
    output = ppt_engine.render_pptx({"slides": [{"type": "content", "title": "新标题",
        "points": ["第一项内容", "第二项内容", "第三项内容"]}]},
        template, base_pptx=buf.getvalue(), warnings=warnings)
    text = "\n".join(shape.text for slide in Presentation(BytesIO(output)).slides
                     for shape in slide.shapes if shape.has_text_frame)
    assert all(point in text for point in ("第一项内容", "第二项内容", "第三项内容"))
    assert not any("已省略" in warning for warning in warnings)


def test_failed_learned_page_falls_back_without_replacing_other_pages(monkeypatch):
    from io import BytesIO
    from pptx import Presentation
    from app.application.ppt import ppt_engine
    base = _make_pptx_bytes([("模板标题", ["模板正文"])])
    learned = ppt_engine.analyze_template(base)
    layout = {**learned["layouts"][0], "detected_type": "content"}
    original_fill = ppt_engine._fill_learned_slide

    def fill(slide, layout_arg, data, *args, **kwargs):
        if data.get("title") == "第二页":
            raise ValueError("page-specific overflow")
        return original_fill(slide, layout_arg, data, *args, **kwargs)

    monkeypatch.setattr(ppt_engine, "_fill_learned_slide", fill)
    warnings = []
    result = ppt_engine.build_pptx_learned({"slides": [
        {"type": "content", "title": "第一页", "points": ["保留模板页"]},
        {"type": "content", "title": "第二页", "points": ["完整内容"]},
    ]}, ppt_engine.template_to_dict(ppt_engine.BUILTIN_TEMPLATES[0]),
        base, [layout], warnings)
    slides = Presentation(BytesIO(result)).slides
    assert len(slides) == 2
    assert "保留模板页" in " ".join(shape.text for shape in slides[0].shapes if shape.has_text_frame)
    assert "完整内容" in " ".join(shape.text for shape in slides[1].shapes if shape.has_text_frame)
    assert any("第二页" in warning and "可读版式" in warning for warning in warnings)


def test_learned_layout_fills_each_template_region():
    from io import BytesIO
    from PIL import Image
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from app.application.ppt import ppt_engine

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    cover = prs.slides.add_slide(prs.slide_layouts[6])
    cover.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(1)).text = "封面样例"
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    for i, text in enumerate(["{{title}}", "{{card1_title}}", "{{card1_body}}",
                               "{{card2_title}}", "{{card2_body}}"]):
        shape = slide.shapes.add_textbox(Inches(1 + (i // 2) * 2),
                                          Inches(1 + (i % 2)), Inches(2), Inches(.7))
        run = shape.text_frame.paragraphs[0].add_run()
        run.text = text if i != 4 else "{{card2_"
        run.font.size = Pt(24 if i == 0 else 16)
        if i == 4:
            shape.text_frame.paragraphs[0].add_run().text = "body}}"
    picture = BytesIO()
    Image.new("RGB", (4, 4), "navy").save(picture, format="PNG")
    picture.seek(0)
    slide.shapes.add_picture(picture, Inches(7), Inches(1), Inches(1), Inches(1))
    source = BytesIO()
    prs.save(source)
    base = source.getvalue()
    learned = ppt_engine.analyze_template(base)
    ppt_engine.validate_learned_template(learned)
    cards_layout = next(layout for layout in learned["layouts"]
                        if layout["source_slide_index"] == 1)
    assert cards_layout["element_schema"][1]["placeholder_keys"] == ["card1_title"]
    outline = {"slides": [{"type": "content", "title": "新标题", "blocks": {
        "cards": [{"label": "规范执法", "value": "完善流程"},
                  {"label": "业务学习", "value": "定期复盘"}]}}]}
    template = {"colors": learned["colors"], "font": learned["font"]}
    out = ppt_engine.build_pptx_learned(outline, template, base, learned["layouts"])
    rendered = Presentation(BytesIO(out))
    values = [shape.text for shape in rendered.slides[0].shapes if shape.has_text_frame]
    assert "新标题" in values
    assert "规范执法" in values
    assert "完善流程" in values
    assert "业务学习" in values
    assert "定期复盘" in values
    assert sum(shape.shape_type == 13 for shape in rendered.slides[0].shapes) == 1


def test_learned_layout_never_uses_cover_for_unmatched_summary():
    from app.application.ppt import ppt_engine
    layouts = [{"id": "L0", "detected_type": "cover"},
               {"id": "L1", "detected_type": "toc"}]
    assert ppt_engine._pick_layout(layouts, "summary", {}) is None


def test_toc_without_matching_layout_uses_readable_page():
    from io import BytesIO
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from app.application.ppt import ppt_engine

    prs = Presentation()
    prs.slides.add_slide(prs.slide_layouts[6]).shapes.add_textbox(
        Inches(1), Inches(1), Inches(6), Inches(1)).text = "封面样例"
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    for i, text in enumerate(["目录", "示例一", "示例二", "示例三"]):
        shape = slide.shapes.add_textbox(Inches(1), Inches(1 + i), Inches(6), Inches(.7))
        run = shape.text_frame.paragraphs[0].add_run()
        run.text = text
        run.font.size = Pt(24 if i == 0 else 16)
    source = BytesIO()
    prs.save(source)
    base = source.getvalue()
    learned = ppt_engine.analyze_template(base)
    without_toc = [layout for layout in learned["layouts"]
                   if layout.get("detected_type") != "toc"]
    warnings = []
    out = ppt_engine.build_pptx_learned(
        {"slides": [{"type": "toc", "title": "本次汇报", "points": ["背景", "措施", "成效"]}]},
        {"colors": learned["colors"], "font": learned["font"]}, base, without_toc, warnings)
    rendered = Presentation(BytesIO(out))
    text = " ".join(shape.text for shape in rendered.slides[0].shapes if shape.has_text_frame)
    assert all(value in text for value in ("本次汇报", "背景", "措施", "成效"))
    assert "示例" not in text
    assert any("可读版式" in warning for warning in warnings)


def test_learned_layout_distinguishes_timeline_from_process():
    from app.application.ppt import ppt_engine

    arrows = [{"kind": "shape", "shape_type": "CHEVRON"} for _ in range(4)]
    labels = [{"kind": "text", "sample": f"节点{i}", "font_size": 16,
               "x": i / 10, "y": .3, "w": .1} for i in range(8)]
    assert ppt_engine._classify_slide(arrows + labels, 1, 3) == "timeline"
    assert ppt_engine._classify_slide(arrows + labels[:3], 1, 3) == "process"


def test_slide_layout_override_wins_over_template_default():
    slide = {"type": "content", "layout": "L9"}
    skeleton = {"content": "L2"}
    assert ppt_engine.preferred_layout_id(slide, skeleton) == "L9"
    assert ppt_engine.preferred_layout_id({"type": "content"}, skeleton) == "L2"


def test_visual_review_endpoint_returns_page_level_findings(client, accounts):
    doc_id = _blank_doc(client, accounts["a"], "视觉复检")
    dense = "这是用于检查文字密度的长段落" * 18
    outline = {"title": "视觉复检", "slides": [
        {"type": "cover", "title": "视觉复检"},
        {"type": "content", "title": "高密度页面", "points": [dense] * 6},
        {"type": "closing", "title": "谢谢聆听"},
    ]}
    saved = client.put(
        f"{BASE}/ppt/documents/{doc_id}/draft", headers=_hdr(accounts["a"]),
        json={"outline": outline},
    )
    assert saved.status_code == 200, saved.text
    response = client.post(
        f"{BASE}/ppt/documents/{doc_id}/visual-review",
        headers=_hdr(accounts["a"]),
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["pages_checked"] == 3
    assert result["status"] == "review"
    assert any(item["page"] == 2 and item["code"] == "text_density"
               for item in result["issues"])


def test_public_library_image_selected_by_user_appears_in_export(client, accounts):
    from pptx import Presentation

    uploaded = client.post(
        f"{BASE}/ppt/library/images", headers=_hdr(accounts["dev"]),
        data={"name": "普法活动配图", "caption": "普法活动现场", "category": "法治宣传",
              "source": "测试素材", "license_note": "测试环境内使用"},
        files={"file": ("activity.png", _png_bytes(), "image/png")},
    )
    assert uploaded.status_code == 200, uploaded.text
    image_id = uploaded.json()["id"]
    doc_id = _blank_doc(client, accounts["a"], "普法活动")
    headers = _hdr(accounts["a"])
    generated = client.post(f"{BASE}/ppt/generate", headers=headers, json={
        "doc_id": doc_id, "outline": {"title": "普法活动", "material_ids": [image_id],
            "slides": [{"type": "content", "title": "普法活动现场",
                        "points": ["向群众发放普法材料"],
                        "image_name": "普法活动配图"}]},
    })
    assert generated.status_code == 200, generated.text
    exported = client.get(f"{BASE}/ppt/documents/{doc_id}/download", headers=headers)
    assert exported.status_code == 200, exported.text
    deck = Presentation(io.BytesIO(exported.content))
    assert any("PICTURE" in str(shape.shape_type)
               for slide in deck.slides for shape in slide.shapes)


def test_visual_review_respects_document_ownership(client, accounts):
    doc_id = _blank_doc(client, accounts["a"], "私有复检")
    response = client.post(
        f"{BASE}/ppt/documents/{doc_id}/visual-review",
        headers=_hdr(accounts["b"]),
    )
    assert response.status_code == 404


def test_visual_review_accepts_standard_government_layout():
    outline = {"title": "工作汇报", "slides": [
        {"type": "cover", "title": "工作汇报"},
        {"type": "content", "title": "工作情况",
         "points": ["依法履职", "服务群众", "规范管理"]},
        {"type": "closing", "title": "谢谢聆听"},
    ]}
    data = ppt_engine.build_pptx(
        outline, {"colors": ppt_engine.DEFAULT_COLORS,
                  "layouts": ppt_engine.DEFAULT_LAYOUTS})
    result = PPTService.review_pptx_visuals(data)
    assert result == {"status": "passed", "pages_checked": 3, "issues": []}


def test_visual_review_accepts_clipped_background_picture_but_flags_text():
    from PIL import Image
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    sample = io.BytesIO()
    Image.new("RGB", (80, 20), "blue").save(sample, format="PNG")
    sample.seek(0)
    slide.shapes.add_picture(sample, Inches(0), Inches(7.3),
                             Inches(13.333), Inches(.35))
    data = io.BytesIO()
    prs.save(data)
    assert PPTService.review_pptx_visuals(data.getvalue())["issues"] == []

    slide.shapes.add_textbox(Inches(12.9), Inches(1), Inches(.8), Inches(.5)).text = "越界文字"
    data = io.BytesIO()
    prs.save(data)
    assert any(issue["code"] == "out_of_bounds" for issue in
               PPTService.review_pptx_visuals(data.getvalue())["issues"])


def test_generation_does_not_save_a_deck_with_severe_visual_errors(
        client, accounts, monkeypatch):
    from pptx import Presentation
    from pptx.util import Inches

    doc_id = _blank_doc(client, accounts["a"], "待校验的演示文稿")
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.shapes.add_textbox(Inches(12), Inches(1), Inches(2), Inches(.5)).text = "越界内容"
    broken = io.BytesIO()
    prs.save(broken)
    monkeypatch.setattr(PPTService, "_render_pptx_bytes",
                        lambda self, *_args, **_kwargs: (broken.getvalue(), "test"))
    response = client.post(
        f"{BASE}/ppt/generate", headers=_hdr(accounts["a"]),
        json={"doc_id": doc_id, "outline": {"title": "测试", "slides": [
            {"type": "content", "title": "测试", "points": ["正常要点"]},
        ]}},
    )
    assert response.status_code == 422, response.text
    assert "越界" in response.text
    assert client.get(f"{BASE}/ppt/documents/{doc_id}/download",
                      headers=_hdr(accounts["a"])).status_code != 200


def test_selected_template_recovers_from_severe_visual_error(
        client, accounts, monkeypatch):
    from pptx import Presentation
    from pptx.util import Inches

    headers = _hdr(accounts["a"])
    template = client.post(f"{BASE}/ppt/templates", headers=headers, json={
        "name": "回退校验模板", "category": "汇报",
    })
    assert template.status_code == 200, template.text
    doc_id = _blank_doc(client, accounts["a"], "模板回退")
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.shapes.add_textbox(Inches(12), Inches(1), Inches(2), Inches(.5)).text = "越界内容"
    broken = io.BytesIO()
    prs.save(broken)
    monkeypatch.setattr(PPTService, "_render_pptx_bytes",
                        lambda self, *_args, **_kwargs: (broken.getvalue(), "test"))
    response = client.post(f"{BASE}/ppt/generate", headers=headers,
                           json={"doc_id": doc_id, "template_id": template.json()["id"],
                                 "outline": {"title": "测试", "slides": [
                                     {"type": "content", "title": "工作情况",
                                      "points": ["依法履职", "规范管理"]},
                                 ]}})
    assert response.status_code == 200, response.text
    assert any("重新排版" in warning for warning in response.json()["warnings"])
    saved = client.get(f"{BASE}/ppt/documents/{doc_id}/download", headers=headers)
    assert saved.status_code == 200
    assert not any(item["severity"] == "error" for item in
                   PPTService.review_pptx_visuals(saved.content)["issues"])
