"""Create the first system administrator from the deployment host.

Run from ``server/``:
    python -m scripts.create_admin

The password is read with getpass and is never accepted as a CLI argument, so it does
not leak into shell history/process listings. The command only works while user count
is zero; subsequent users must be created through the authenticated admin UI/API.
"""
from __future__ import annotations

import argparse
import getpass
import sys

from app.application.identity.service import AuthService
from app.infrastructure.database import SessionLocal
from app.infrastructure.repositories.identity import SqlAlchemyUserRepository


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="初始化首个系统管理员（仅本机命令行）")
    parser.add_argument("--username", default="admin", help="管理员用户名，默认 admin")
    parser.add_argument("--email", required=True, help="管理员邮箱")
    parser.add_argument("--real-name", default="系统管理员", help="姓名")
    parser.add_argument("--department-code", default="", help="可选：科室 code")
    return parser.parse_args()


def main() -> int:
    args = _args()
    password = getpass.getpass("设置管理员密码: ")
    confirm = getpass.getpass("再次输入密码: ")
    if password != confirm:
        print("两次输入的密码不一致", file=sys.stderr)
        return 2

    db = SessionLocal()
    try:
        service = AuthService(SqlAlchemyUserRepository(db), db=db)
        if not service.is_first_user():
            print("系统已有用户；首管理员初始化命令已失效。", file=sys.stderr)
            return 3
        _token, user = service.register_first(
            args.username,
            args.email,
            password,
            real_name=args.real_name,
            department_code=args.department_code,
        )
        print(f"首个系统管理员已创建：{user.username}（{user.id}）")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
