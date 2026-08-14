#!/usr/bin/env python3
"""
司法局智能写作助手 - 集成测试
覆盖：用户、模板、知识库、文档、写作全流程
"""
import requests
import json
import sys
import tempfile

BASE_URL = "http://localhost:8000/api/v1"

class TestClient:
    def __init__(self):
        self.token = None
        self.user = None
        self.session = requests.Session()
    
    def _headers(self):
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h
    
    def post(self, path, data=None):
        url = f"{BASE_URL}{path}"
        r = self.session.post(url, json=data or {}, headers=self._headers())
        return r
    
    def get(self, path):
        url = f"{BASE_URL}{path}"
        r = self.session.get(url, headers=self._headers())
        return r

client = TestClient()
passed = 0
failed = 0

def test(name, condition, detail=""):
    global passed, failed
    if condition:
        print(f"  ✅ {name}")
        passed += 1
    else:
        print(f"  ❌ {name}: {detail}")
        failed += 1

# ==================== 测试开始 ====================
print("=" * 60)
print("司法局智能写作助手 - 集成测试")
print("=" * 60)

# ---------- 1. 用户系统 ----------
print("\n【1. 用户系统】")

r = client.get("/auth/check-first-user")
test("检查首次用户", r.status_code == 200, r.text)
is_first = r.json().get("is_first", False)

if is_first:
    r = client.post("/auth/register-first", {
        "username": "superadmin",
        "email": "admin@judicial.gov.cn",
        "password": "admin123",
        "real_name": "系统管理员",
        "department": "信息中心",
        "role": "developer"
    })
    test("首次注册系统管理员", r.status_code == 200, f"{r.status_code}: {r.text}")
    if r.status_code == 200:
        client.token = r.json()["access_token"]
        client.user = r.json()["user"]
else:
    r = client.post("/auth/login", {
        "username": "superadmin",
        "password": "admin123"
    })
    test("系统管理员登录", r.status_code == 200, f"{r.status_code}: {r.text}")
    if r.status_code == 200:
        client.token = r.json()["access_token"]
        client.user = r.json()["user"]

if not client.token:
    print("\n❌ 无法获取 token，后续测试跳过")
    sys.exit(1)

r = client.get("/auth/me")
test("获取当前用户信息", r.status_code == 200 and r.json().get("role") == "developer", r.text)

# ---------- 2. 知识管理员 ----------
print("\n【2. 知识管理员】")

r = client.post("/auth/register", {
    "username": "kbadmin",
    "email": "kb@judicial.gov.cn",
    "password": "kb123456",
    "real_name": "知识管理员",
    "department": "办公室",
    "role": "knowledge_admin"
})
test("注册知识管理员", r.status_code == 200, f"{r.status_code}: {r.text}")

kb_client = TestClient()
r = kb_client.post("/auth/login", {"username": "kbadmin", "password": "kb123456"})
test("知识管理员登录", r.status_code == 200, r.text)
if r.status_code == 200:
    kb_client.token = r.json()["access_token"]

# ---------- 3. 普通用户 ----------
print("\n【3. 普通用户】")

r = client.post("/auth/register", {
    "username": "user01",
    "email": "user01@judicial.gov.cn",
    "password": "user123456",
    "real_name": "张三",
    "department": "社区矫正科",
    "role": "user"
})
test("注册普通用户", r.status_code == 200, f"{r.status_code}: {r.text}")

user_client = TestClient()
r = user_client.post("/auth/login", {"username": "user01", "password": "user123456"})
test("普通用户登录", r.status_code == 200, r.text)
if r.status_code == 200:
    user_client.token = r.json()["access_token"]

# ---------- 4. 写作模板 ----------
print("\n【4. 写作模板】")

r = client.post("/templates/init")
test("系统管理员初始化模板", r.status_code == 200, f"{r.status_code}: {r.text}")

if kb_client.token:
    r = kb_client.post("/templates/init")
    test("知识管理员初始化模板", r.status_code == 200, f"{r.status_code}: {r.text}")

r = client.get("/templates/")
test("获取模板列表", r.status_code == 200 and len(r.json()) > 0, f"数量: {len(r.json()) if r.status_code == 200 else 0}")

if r.status_code == 200 and len(r.json()) > 0:
    tmpl = r.json()[0]
    test("模板包含 base_type", "base_type" in tmpl, str(tmpl.keys()))
    test("模板包含 writing_style", "writing_style" in tmpl, str(tmpl.keys()))
    test("模板包含 word_count", "word_count" in tmpl, str(tmpl.keys()))
    test("模板包含 params_schema", "params_schema" in tmpl and len(tmpl["params_schema"]) > 0, str(tmpl.get("params_schema")))

if kb_client.token:
    r = kb_client.post("/templates/", {
        "name": "测试通知模板",
        "category": "通知公告",
        "base_type": "通知",
        "description": "用于测试的自定义通知模板",
        "icon": "Bell",
        "params_schema": [
            {"name": "title", "label": "通知标题", "type": "input", "required": True, "placeholder": "如：关于开展XX活动的通知"},
            {"name": "recipient", "label": "通知对象", "type": "input", "required": True, "placeholder": "如：各区县司法局"},
            {"name": "content", "label": "具体事项", "type": "textarea", "required": True, "placeholder": "请详细说明"}
        ],
        "content_template": "通知类公文，包含标题、主送机关、正文、落款和成文日期。",
        "system_prompt": "你是一位资深的司法行政公文写作专家，擅长撰写通知。",
        "writing_style": "正式公文",
        "word_count": 800,
        "need_red_header": False,
        "need_signature": True,
        "need_date": True,
        "need_doc_number": False
    })
    test("知识管理员创建自定义模板", r.status_code == 200, f"{r.status_code}: {r.text}")

# ---------- 5. 知识库 ----------
print("\n【5. 知识库】")

r = client.post("/knowledge/create", {"name": "司法局公共资料库", "description": "全局共享的法规公文资料"})
test("系统管理员创建公共知识库", r.status_code == 200, f"{r.status_code}: {r.text}")
public_kb_id = r.json().get("id") if r.status_code == 200 else None

if user_client.token:
    r = user_client.post("/knowledge/create", {"name": "我的个人资料", "description": "个人收藏的文档"})
    test("普通用户创建个人知识库", r.status_code == 200, f"{r.status_code}: {r.text}")
    personal_kb_id = r.json().get("id") if r.status_code == 200 else None
    if r.status_code == 200:
        test("个人库类型为 personal", r.json().get("type") == "personal", r.json().get("type"))
else:
    personal_kb_id = None

# ---------- 6. 文档上传 ----------
print("\n【6. 文档上传】")

with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
    f.write("关于开展社区矫正工作的通知\n\n各相关单位：\n\n为进一步加强社区矫正工作...")
    test_file_path = f.name

if public_kb_id:
    with open(test_file_path, 'rb') as f:
        r = client.session.post(
            f"{BASE_URL}/knowledge/upload?kb_id={public_kb_id}",
            files={"file": ("test_doc.txt", f, "text/plain")},
            headers={"Authorization": f"Bearer {client.token}"}
        )
    test("管理员上传文档到公共库", r.status_code == 200, f"{r.status_code}: {r.text}")
    if r.status_code == 200:
        test("管理员文档直接发布", r.json().get("status") == "published", r.json().get("status"))

if personal_kb_id and user_client.token:
    with open(test_file_path, 'rb') as f:
        r = user_client.session.post(
            f"{BASE_URL}/knowledge/upload?kb_id={personal_kb_id}",
            files={"file": ("test_doc.txt", f, "text/plain")},
            headers={"Authorization": f"Bearer {user_client.token}"}
        )
    test("普通用户上传文档到个人库", r.status_code == 200, f"{r.status_code}: {r.text}")
    if r.status_code == 200:
        test("个人库文档直接发布", r.json().get("status") == "published", r.json().get("status"))

if public_kb_id and user_client.token:
    with open(test_file_path, 'rb') as f:
        r = user_client.session.post(
            f"{BASE_URL}/knowledge/upload?kb_id={public_kb_id}",
            files={"file": ("test_doc.txt", f, "text/plain")},
            headers={"Authorization": f"Bearer {user_client.token}"}
        )
    test("普通用户上传文档到公共库", r.status_code == 200, f"{r.status_code}: {r.text}")
    if r.status_code == 200:
        test("公共库文档待审核", r.json().get("status") == "pending", r.json().get("status"))

# ---------- 7. 文档审核 ----------
print("\n【7. 文档审核】")

if kb_client.token and public_kb_id:
    r = kb_client.get("/knowledge/pending")
    test("知识管理员查看待审核", r.status_code == 200, r.text)
    
    if r.status_code == 200 and len(r.json()) > 0:
        doc_id = r.json()[0]["id"]
        r = kb_client.post("/knowledge/review", {"doc_id": doc_id, "action": "approved", "comment": "审核通过"})
        test("知识管理员审核通过", r.status_code == 200, f"{r.status_code}: {r.text}")
    else:
        test("知识管理员审核", False, "没有待审核文档")
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write("测试待审核文档")
        test_file2 = f.name
    if user_client.token:
        with open(test_file2, 'rb') as f:
            r = user_client.session.post(
                f"{BASE_URL}/knowledge/upload?kb_id={public_kb_id}",
                files={"file": ("test2.txt", f, "text/plain")},
                headers={"Authorization": f"Bearer {user_client.token}"}
            )
        if r.status_code == 200:
            doc_id2 = r.json().get("doc_id")
            r = client.post("/knowledge/review", {"doc_id": doc_id2, "action": "approved"})
            test("系统管理员不能审核", r.status_code == 403, f"期望403，实际{r.status_code}")

# ---------- 8. 智能写作 ----------
print("\n【8. 智能写作】")

r = client.get("/templates/")
if r.status_code == 200 and len(r.json()) > 0:
    r = client.post("/chat/send", {
        "message": "请根据以下信息生成公文。",
        "session_id": None,
        "use_rag": True,
        "system_prompt": "你是一位资深的司法行政公文写作专家。",
        "template_category": "通知"
    })
    test("模板生成接口调用", r.status_code == 200, f"{r.status_code}: {r.text[:100]}")
    if r.status_code == 200:
        test("生成结果非空", len(r.json().get("reply", "")) > 0, "reply为空")
        test("返回 session_id", r.json().get("session_id") is not None, "无session_id")
else:
    test("智能写作测试", False, "无可用模板")

# ---------- 9. 会话历史 ----------
print("\n【9. 会话历史】")

r = client.get("/chat/sessions")
test("获取会话列表", r.status_code == 200, r.text)
if r.status_code == 200:
    sessions = r.json()
    test("会话列表非空", len(sessions) > 0, f"数量: {len(sessions)}")
    if len(sessions) > 0:
        sid = sessions[0]["id"]
        r = client.get(f"/chat/sessions/{sid}/messages")
        test("获取会话消息", r.status_code == 200, r.text)

# ---------- 10. 统计接口 ----------
print("\n【10. 统计接口】")

r = client.get("/knowledge/stats")
test("管理后台统计数据", r.status_code == 200, r.text)
if r.status_code == 200:
    data = r.json()
    test("stats 包含 user_count", "user_count" in data, str(data.keys()))
    test("stats 包含 doc_count", "doc_count" in data, str(data.keys()))
    test("stats 包含 session_count", "session_count" in data, str(data.keys()))
    test("stats 包含 kb_count", "kb_count" in data, str(data.keys()))

# ==================== 测试报告 ====================
print("\n" + "=" * 60)
print(f"测试完成：通过 {passed} / 失败 {failed} / 总计 {passed + failed}")
print("=" * 60)

if failed > 0:
    sys.exit(1)
