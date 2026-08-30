"""迁移包装器：生产环境调用 alembic upgrade head。

开发环境可在 .env 中启用 DB_AUTO_MIGRATE=true 让 lifespan 自动建表，
但生产部署必须执行 `python -m app.migrations.migrator upgrade` 或
`alembic upgrade head`。
"""
import argparse
import logging
import sys

from alembic.config import Config
from alembic import command

logger = logging.getLogger(__name__)


def _alembic_cfg() -> Config:
    cfg = Config("alembic.ini")
    return cfg


def upgrade(revision: str = "head") -> None:
    command.upgrade(_alembic_cfg(), revision)
    logger.info("数据库已升级至 %s", revision)


def downgrade(revision: str) -> None:
    command.downgrade(_alembic_cfg(), revision)
    logger.info("数据库已回退至 %s", revision)


def revision(message: str, autogenerate: bool = False) -> None:
    command.revision(_alembic_cfg(), message=message, autogenerate=autogenerate)
    logger.info("已生成迁移脚本: %s", message)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="司法智能写作助手数据库迁移")
    parser.add_argument("command", choices=["upgrade", "downgrade", "revision"])
    parser.add_argument("-r", "--revision", default="head")
    parser.add_argument("-m", "--message", default="")
    parser.add_argument("--autogenerate", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    if args.command == "upgrade":
        upgrade(args.revision)
    elif args.command == "downgrade":
        downgrade(args.revision)
    elif args.command == "revision":
        if not args.message:
            sys.exit("请使用 -m 指定迁移说明")
        revision(args.message, args.autogenerate)
