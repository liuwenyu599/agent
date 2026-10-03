"""数据库引擎与会话管理。默认 SQLite，可通过 DATABASE_URL 切换。"""
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

settings.DATA_DIR.mkdir(parents=True, exist_ok=True)

_connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}

engine = create_engine(settings.DATABASE_URL, connect_args=_connect_args, pool_pre_ping=True)


if settings.DATABASE_URL.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _record):  # noqa: ANN001, ANN202
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    """FastAPI 依赖：请求级 Session。"""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def configure_engine(database_url: str | None = None, data_dir: str | None = None):
    """重建共享引擎，并将 *同一个* SessionLocal 重新绑定到新引擎。

    测试隔离专用：每个测试模块在 import 时通过 ``os.environ.setdefault`` 声明自己的
    临时库，但 ``engine`` 是进程级单例，会在「第一个 import 本模块的模块」处被锁定，
    后续模块的 ``setdefault`` 失效。此函数从「当前环境 / 显式参数」重建引擎，使隔离与
    import 顺序无关。生产代码不会调用，行为安全。

    关键点：不重新赋值 ``SessionLocal`` 这个名字，而是 ``SessionLocal.configure(
    bind=new_engine)`` 复用同一个 sessionmaker 对象，这样无论测试模块 / 应用代码是
    局部还是全局引用 ``SessionLocal``，都会透明命中新引擎，避免「换库后本地引用仍指向
    旧引擎」导致的脏读 / 表缺失。

    Args:
        database_url: 目标连接串；缺省沿用 ``settings.DATABASE_URL``（即当前环境值）。
        data_dir: 目标数据目录；提供时同步更新 ``settings.DATA_DIR`` 并建目录。
    """
    global engine
    if data_dir is not None:
        settings.DATA_DIR = Path(data_dir)
        settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    url = database_url or settings.DATABASE_URL
    settings.DATABASE_URL = url

    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    new_engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True)

    if url.startswith("sqlite"):
        @event.listens_for(new_engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _record):  # noqa: ANN001, ANN202
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    # 复用同一个 sessionmaker 对象，仅重绑 bind，使所有（局部/全局）引用透明换库。
    SessionLocal.configure(bind=new_engine)
    previous = engine
    engine = new_engine
    try:
        previous.dispose()
    except Exception:  # 首建或已释放时静默忽略
        pass
    # 在刚绑定的库上建表（测试模块自身 import 期的 create_all 可能落在旧引擎上）。
    from app.infrastructure.database import Base

    Base.metadata.create_all(bind=engine)
    return engine
