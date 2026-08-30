"""FastAPI 应用入口：装配全部模块、路由、静态资源与生命周期钩子。"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.infrastructure.ai import get_llm_gateway
from app.infrastructure.database import Base, SessionLocal, engine
from app.infrastructure.rag import get_embedder, get_vector_store

setup_logging()
logger = get_logger(__name__)

# ---- 导入全部 ORM 模型完成注册（Base.metadata.create_all 需要） ----
from app.infrastructure.database.models import (  # noqa: E402,F401
    chat,
    format_check,
    identity,
    knowledge,
    ppt,
    references,
    templates,
    workflow,
)


def _ensure_directories() -> None:
    """确保运行时数据目录存在。"""
    settings.ensure_dirs()
    # PPT 子目录
    for sub in ("tpl_src", "tpl_prev", "materials", "generated", "tmp"):
        (settings.ppt_dir / sub).mkdir(parents=True, exist_ok=True)
    (settings.uploads_dir / "chat").mkdir(parents=True, exist_ok=True)
    (settings.DATA_DIR / "format-check").mkdir(parents=True, exist_ok=True)


def _init_database() -> None:
    """自动迁移：优先 Alembic，失败或无迁移脚本时回退到 Base.metadata.create_all。"""
    if not settings.DB_AUTO_MIGRATE:
        return
    try:
        from app.migrations import migrator
        migrator.upgrade("head")
        logger.info("数据库已自动升级至最新迁移版本")
        return
    except Exception as e:
        logger.warning("Alembic 自动升级失败，回退到 create_all: %s", e)
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("数据库表结构已自动创建/更新（create_all 回退）")
    except Exception as e:
        logger.error("自动建表失败: %s", e)
        raise


def _init_facilities() -> None:
    """初始化 AI Gateway / Embedding / VectorStore 等外部设施（懒加载 + 连接检测）。"""
    try:
        get_llm_gateway()
        logger.info("AI Gateway 初始化完成")
    except Exception as e:
        logger.warning("AI Gateway 初始化警告: %s", e)
    try:
        get_embedder()
        get_vector_store()
        logger.info("Embedding / VectorStore 初始化完成")
    except Exception as e:
        logger.warning("RAG 设施初始化警告: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _ensure_directories()
    _init_database()
    _init_facilities()
    # 预置内置模板（幂等）：存在系统管理员则用之，否则初始化时跳过，由首次注册后调用
    try:
        db = SessionLocal()
        from app.application.identity.service import AuthService
        from app.application.templates.service import TemplateService
        from app.infrastructure.repositories.identity import SqlAlchemyUserRepository
        user_repo = SqlAlchemyUserRepository(db)
        auth = AuthService(user_repo)
        if auth.is_first_user():
            logger.info("系统尚无用户，内置模板待首次注册后自动初始化")
        else:
            admin = user_repo.get_by_username("admin")
            if admin:
                TemplateService(db).init_builtin(admin)
                logger.info("内置模板已初始化")
        db.close()
    except Exception as e:
        logger.warning("内置模板初始化警告: %s", e)
    yield
    # 关闭引擎连接池
    engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Judicial AI Server",
        version="1.0.0",
        description="司法智能写作助手 - 中心服务器",
        lifespan=lifespan,
    )

    # CORS：生产环境请配置具体来源
    origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()] or ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 静态资源：上传文件/图片
    uploads_dir = Path(settings.uploads_dir)
    uploads_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=str(uploads_dir)), name="uploads")

    # 核心路由：全部挂在 /api/v1
    from app.interfaces import (
        auth,
        chat,
        format_check,
        knowledge,
        ppt,
        references,
        templates,
        users,
        workflow,
    )

    routers = [
        auth.router,
        users.router,
        chat.router,
        format_check.router,
        knowledge.router,
        references.router,
        templates.router,
        workflow.router,
        ppt.router,
    ]
    for r in routers:
        app.include_router(r, prefix="/api/v1")

    @app.get("/health")
    def health():
        return {"status": "ok", "version": "1.0.0"}

    @app.get("/")
    def root():
        return {"service": "Judicial AI Server", "docs": "/docs"}

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=False)
