# judicial_app/server 架构约定（所有模块必须遵守）

技术栈：Python 3.11+ / FastAPI / SQLAlchemy 2.0（`Mapped`/`mapped_column` 新风格）/ SQLite（默认，`DATABASE_URL` 可换）。
所有路由挂在 `/api/v1` 前缀下（main.py 统一加），router 自身的 prefix 不含 `/api/v1`。

## 分层（Clean Architecture + DDD，模块化单体）

```
app/
  core/            # 配置/异常/日志/安全（已存在，勿改接口）
  domain/<m>/      # entities.py（@dataclass 纯领域对象）+ repositories.py（Repository ABC）
                   # 禁止 import fastapi / sqlalchemy / requests / openai 等框架与 SDK
  application/
    ports.py       # 跨模块端口协议（LLMGateway / Embedder / VectorStore，Protocol）
    <m>/service.py # 用例服务：只依赖 domain 端口 + application.ports，不碰 SQLAlchemy/FastAPI
    <m>/dto.py     # Pydantic v2 请求/响应模型
  infrastructure/
    database/
      base.py      # Base, IdMixin, TimestampMixin, SoftDeleteMixin, generate_uuid
      session.py   # engine, SessionLocal, get_db
      models/<m>.py     # ORM 模型，命名 XxxModel，继承 Base + IdMixin/TimestampMixin
      models/__init__.py # 注册表：import 所有模型模块（由装配者维护，子模块勿动）
    repositories/<m>.py # SqlAlchemyXxxRepository，构造收 Session，内部做 ORM<->entity 映射
    ai/            # AI Gateway：base(工厂) / qwen.py / mock.py
    rag/           # embedder.py / vector_store.py（实现 application.ports）
    storage/       # 本地文件存储
    backup/        # 备份
    audit/         # 审计落地
  interfaces/
    deps.py        # get_current_user / require_knowledge_admin / require_developer / require_admin_or_above
    <m>.py         # FastAPI router，薄层：校验 -> 调 application service -> 返回
  migrations/      # 版本化轻量迁移（migrator.py 统一入口）
  main.py          # 装配（由装配者维护）
```

## 约定

- 领域实体用 `@dataclass`，id 为 str；ORM 主键用 `IdMixin`（String(36)，`generate_uuid()` 返回带连字符 uuid4）。
- Repository ABC 继承 `app.domain.base.Repository[T]`（get/add/delete），按需加查询方法。
- SQLAlchemy 仓储实现：`class SqlAlchemyXxxRepository(XxxRepository)`，`__init__(self, db: Session)`，提供 `_to_entity`/`_apply` 映射。
- 业务错误抛 `app.core.exceptions` 里的 `AppError/NotFoundError/PermissionDeniedError/ConflictError/AIServiceError`。
- 日志用 `app.core.logging.get_logger(__name__)`，禁止 print，禁止记录密码/token/文件内容。
- 路由依赖注入示例：

```python
from app.infrastructure.database import get_db
from app.interfaces.deps import get_current_user
from app.domain.identity.entities import User

def get_xxx_service(db: Session = Depends(get_db)) -> XxxService:
    return XxxService(SqlAlchemyXxxRepository(db), ...)

@router.get("/")
def list_(user: User = Depends(get_current_user), svc: XxxService = Depends(get_xxx_service)): ...
```

- RBAC 角色：`developer`（系统管理员）> `knowledge_admin`（知识管理员）> `user`。`require_admin_or_above` 允许 `{"developer","knowledge_admin","admin"}`（兼容旧数据）。
- 旧系统行为以 `/home/lwy/judicial-ai/backend`（只读）为准；API 响应结构与旧 Web 端保持一致，desktop 端已按这些契约实现（见 `desktop/.../core/network/Endpoints.kt`）。
- 外部资源（模型服务、embedding 模型）在单测中一律用 mock（`AI_PROVIDER=mock`、`EMBEDDING_PROVIDER=mock`）。
