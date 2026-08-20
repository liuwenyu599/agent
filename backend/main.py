from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

from backend.api import auth, chat, knowledge, user, templates, format_check, workflow, references, ppt
from backend.database import models_ppt  # noqa: F401  注册 ppt_materials / ppt_documents 两张表
from backend.database import models_reference  # noqa: F401  注册 template_references / task_references 两张表
from backend.middleware.logging import LoggingMiddleware
from backend.database.postgres import engine
from backend.database.models import Base

Base.metadata.create_all(bind=engine)
def _auto_migrate():
    """轻量迁移：为已有表补充新增列（create_all 不会修改已存在的表）"""
    from sqlalchemy import text, inspect
    insp = inspect(engine)
    
    # chat_messages.attachments
    try:
        cols = [c["name"] for c in insp.get_columns("chat_messages")]
        if "attachments" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE chat_messages ADD COLUMN attachments JSON"))
            print("[迁移] chat_messages 已新增 attachments 列")
    except Exception as e:
        print(f"[迁移] chat_messages 跳过/失败: {e}")
    
    # writing_templates 新版字段
    _wt_new_cols = [
        ("template_kind", "VARCHAR(20) DEFAULT 'official_doc'"),
        ("tags", "JSON"),
        ("scene", "VARCHAR(300)"),
        ("writing_guide", "TEXT"),
        ("structure", "JSON"),
        ("kb_ids", "JSON"),
        ("visibility", "VARCHAR(20) DEFAULT 'official'"),
        ("share_scope", "VARCHAR(20) DEFAULT 'all'"),
        ("share_departments", "JSON"),
        ("share_roles", "JSON"),
        ("is_draft", "BOOLEAN DEFAULT 0"),
    ]
    try:
        cols = [c["name"] for c in insp.get_columns("writing_templates")]
        with engine.begin() as conn:
            for col_name, col_def in _wt_new_cols:
                if col_name not in cols:
                    conn.execute(text(f"ALTER TABLE writing_templates ADD COLUMN {col_name} {col_def}"))
                    print(f"[迁移] writing_templates 已新增 {col_name} 列")
    except Exception as e:
        print(f"[迁移] writing_templates 跳过/失败: {e}")

    # workflow_instances.workflow_context
    try:
        cols = [c["name"] for c in insp.get_columns("workflow_instances")]
        if "workflow_context" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE workflow_instances ADD COLUMN workflow_context JSON"))
            print("[迁移] workflow_instances 已新增 workflow_context 列")
    except Exception as e:
        print(f"[迁移] workflow_instances 跳过/失败: {e}")

    # ppt_documents V2 新增列（我的PPT：模板关联/状态/收藏等）
    _ppt_doc_cols = [
        ("template_id", "VARCHAR(36)"),
        ("subtitle", "VARCHAR(300) DEFAULT ''"),
        ("source_content", "TEXT"),
        ("status", "VARCHAR(20) DEFAULT 'draft'"),
        ("is_favorite", "BOOLEAN DEFAULT 0"),
        ("slide_count", "INTEGER DEFAULT 0"),
    ]
    try:
        cols = [c["name"] for c in insp.get_columns("ppt_documents")]
        with engine.begin() as conn:
            for col_name, col_def in _ppt_doc_cols:
                if col_name not in cols:
                    conn.execute(text(f"ALTER TABLE ppt_documents ADD COLUMN {col_name} {col_def}"))
                    print(f"[迁移] ppt_documents 已新增 {col_name} 列")
    except Exception as e:
        print(f"[迁移] ppt_documents 跳过/失败: {e}")

    # ppt_templates 新增列（builtin_id / 上传模板相关字段，兼容旧版建表）
    _ppt_tpl_cols = [
        ("builtin_id", "VARCHAR(50)"),
        ("category", "VARCHAR(50) DEFAULT '工作汇报'"),
        ("description", "VARCHAR(300)"),
        ("is_official", "BOOLEAN DEFAULT 0"),
        ("created_by", "VARCHAR(36)"),
        ("colors", "JSON"),
        ("font", "VARCHAR(50) DEFAULT '微软雅黑'"),
        ("layouts", "JSON"),
        ("source_file", "VARCHAR(500)"),
        ("use_count", "INTEGER DEFAULT 0"),
        ("layout_library", "JSON"),
    ]
    try:
        cols = [c["name"] for c in insp.get_columns("ppt_templates")]
        with engine.begin() as conn:
            for col_name, col_def in _ppt_tpl_cols:
                if col_name not in cols:
                    conn.execute(text(f"ALTER TABLE ppt_templates ADD COLUMN {col_name} {col_def}"))
                    print(f"[迁移] ppt_templates 已新增 {col_name} 列")
    except Exception as e:
        print(f"[迁移] ppt_templates 跳过/失败: {e}")
_auto_migrate()

app = FastAPI(title="司法智能办公辅助平台 V1.0", description="基于大语言模型的司法公文智能写作系统", version="1.1.0")

app.add_middleware(LoggingMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

app.include_router(auth.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(knowledge.router, prefix="/api/v1")
app.include_router(user.router, prefix="/api/v1")
app.include_router(templates.router, prefix="/api/v1")
app.include_router(format_check.router, prefix="/api/v1")
app.include_router(workflow.router, prefix="/api/v1")
app.include_router(references.router, prefix="/api/v1")
app.include_router(ppt.router, prefix="/api/v1")

uploads_dir = "/home/lwy/judicial-ai/uploads"
os.makedirs(uploads_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")

@app.on_event("startup")
async def startup_event():
    print("=" * 50)
    print("司法智能办公辅助平台 V1.0服务启动")
    print("API 文档: http://localhost:8000/docs")
    print("=" * 50)

@app.on_event("shutdown")
async def shutdown_event():
    print("服务关闭")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)