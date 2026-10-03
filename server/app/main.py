"""FastAPI 应用入口：装配全部模块、路由与生命周期钩子。"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

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
    doc_number,
    document,
    format_check,
    identity,
    knowledge,
    ppt,
    references,
    templates,
    training,
    workflow,
    writing_task,
)


def _ensure_directories() -> None:
    settings.ensure_dirs()
    for sub in ("tpl_src", "tpl_prev", "materials", "generated", "tmp"):
        (settings.ppt_dir / sub).mkdir(parents=True, exist_ok=True)
    (settings.uploads_dir / "chat").mkdir(parents=True, exist_ok=True)
    (settings.DATA_DIR / "format-check").mkdir(parents=True, exist_ok=True)


def _init_database() -> None:
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
    try:
        db = SessionLocal()
        from app.application.identity.service import AuthService
        from app.application.templates.service import TemplateService
        from app.infrastructure.repositories.identity import SqlAlchemyUserRepository
        user_repo = SqlAlchemyUserRepository(db)
        auth = AuthService(user_repo)
        if auth.is_first_user():
            logger.warning("系统尚无用户，请在部署主机执行：python -m scripts.create_admin")
        else:
            admin = user_repo.get_by_username("admin")
            if admin:
                TemplateService(db).init_builtin(admin)
                logger.info("内置模板已初始化")
        db.close()
    except Exception as e:
        logger.warning("内置模板初始化警告: %s", e)
    try:
        db = SessionLocal()
        from app.application.organization.service import OrganizationService
        svc = OrganizationService(db)
        svc.ensure_seeded()
        svc.backfill_user_codes()
        db.close()
    except Exception as e:
        logger.warning("组织架构初始化警告: %s", e)
    yield
    engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Judicial AI Server",
        version="1.0.0",
        description="司法智能写作助手 - 中心服务器",
        lifespan=lifespan,
    )

    origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()] or ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from app.core.monitoring import metrics_response, prometheus_middleware, readiness
    app.middleware("http")(prometheus_middleware)

    from app.interfaces import (
        auth,
        chat,
        dashboard,
        documents,
        files,
        format_check,
        knowledge,
        organization,
        ppt,
        preferences,
        references,
        system,
        templates,
        users,
        writing_tasks,
        workflow,
    )

    routers = [
        auth.router,
        users.router,
        chat.router,
        documents.router,
        files.router,
        format_check.router,
        knowledge.router,
        references.router,
        templates.router,
        writing_tasks.router,
        workflow.router,
        ppt.router,
        dashboard.router,
        system.router,
        organization.router,
        preferences.router,
    ]
    for r in routers:
        app.include_router(r, prefix="/api/v1")

    from fastapi.exceptions import RequestValidationError
    from app.interfaces.preferences import validation_error_handler
    app.add_exception_handler(RequestValidationError, validation_error_handler)

    @app.get("/health")
    def health():
        return {"status": "ok", "version": "1.0.0"}

    @app.get("/ready")
    def ready():
        ok, checks = readiness()
        if not ok:
            raise HTTPException(status_code=503, detail={"status": "not_ready", "checks": checks})
        return {"status": "ready", "checks": checks}

    @app.get("/metrics", include_in_schema=False)
    def metrics():
        return metrics_response()

    @app.get("/")
    def root():
        return {"service": "Judicial AI Server", "docs": "/docs"}

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=False)