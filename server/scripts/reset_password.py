"""命令行重置账号密码（不经HTTP、不触发登录限流）。

为什么需要
----------
排查「登录尝试过多」时，靠反复调登录接口猜密码是最糟的方式：
`login_rate_limiter` 是进程内单例，10 分钟失败 5 次锁 15 分钟，按 IP + 用户名
双桶计数；一旦锁住，界面只剩 429，反而把真正要验证的信息遮住。

本脚本直接改库并置 `must_change_password=True`，让用户登录后强制改密。

安全约束（重要）
----------------
- 新密码走 `getpass` **交互输入**，不接受命令行参数 ——
  否则会落进 shell history、`ps` 进程列表与本脚本的调用记录。
- **永不打印明文密码**，成功时只回显长度。
- 初始密码**允许弱密码**（与 `AuthService.reset_password` 一致）：
  交接场景常需要"先给个能登上的临时密码"，强度由用户登录后的强制改密兜底。
  需要强密码时加 `--strict`。
- 走 `AuthService.reset_password`，保留密码审计日志（谁、何时、重置了谁）。
- 操作前强制显示账号当前状态，避免改错人。

在服务器上的用法
----------------
    cd /opt/justice-office/deploy
    docker compose --env-file .env run --rm migrate python -m scripts.reset_password admin
"""
from __future__ import annotations

import argparse
import getpass
import sys

from app.application.identity.service import UserService
from app.infrastructure.database import SessionLocal
from app.infrastructure.repositories.identity import SqlAlchemyUserRepository


def _args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="命令行重置账号密码（只影响指定账号）")
    p.add_argument("username", help="要重置密码的用户名")
    p.add_argument("--actor", default="admin",
                   help="操作者账号（写入密码审计日志），须为 developer 角色，默认 admin")
    p.add_argument("--strict", action="store_true",
                   help="按强度规则校验新密码（至少 8 位且含大小写+数字+符号）；"
                        "默认不校验，允许设临时密码")
    p.add_argument("--yes", action="store_true",
                   help="跳过确认（用于非交互脚本；请先单独跑 inspect_account 核对账号）")
    return p.parse_args()


def _prompt_password(strict: bool) -> str:
    """交互读取新密码。strict 时循环要求满足强度规则。"""
    if strict:
        from app.core.security import validate_password_strength
        from app.core.exceptions import AppError
        while True:
            pw = getpass.getpass("新密码（不回显）: ")
            confirm = getpass.getpass("再输一次      : ")
            if pw != confirm:
                print("两次输入不一致，重来。", file=sys.stderr)
                continue
            try:
                validate_password_strength(pw)
                return pw
            except AppError as e:
                # 错误信息只描述规则，不回显密码内容
                print(f"不满足强度要求：{e.message}", file=sys.stderr)

    pw = getpass.getpass("新密码（不回显）: ")
    confirm = getpass.getpass("再输一次      : ")
    if pw != confirm:
        print("两次输入不一致。", file=sys.stderr)
        sys.exit(2)
    if not pw:
        print("密码不能为空。", file=sys.stderr)
        sys.exit(2)
    return pw


def main() -> int:
    args = _args()
    db = SessionLocal()
    try:
        repo = SqlAlchemyUserRepository(db)
        svc = UserService(repo, db=db)
        user = repo.get_by_username(args.username)
        if not user:
            print(f"\n❌ 账号 {args.username} 不存在。", file=sys.stderr)
            print("跑这个看清全部账号的准确拼写：", file=sys.stderr)
            print(f"  python -m scripts.inspect_account {args.username} --list\n",
                  file=sys.stderr)
            return 1

        # 审计要记「谁重置的」。这是命令行直改库，没有登录态的 actor，
        # 所以显式指定一个系统管理员作为操作者；可用 --actor 换成实际执行人。
        actor = repo.get_by_username(args.actor)
        if not actor:
            print(f"\n❌ 操作者账号 {args.actor} 不存在，无法写审计。", file=sys.stderr)
            print("   可用 --actor 指定库中任一 developer 角色账号。", file=sys.stderr)
            return 1
        if actor.role != "developer":
            print(f"\n❌ 操作者 {args.actor} 的角色是 {actor.role}，"
                  f"必须是 developer 才能重置他人密码。", file=sys.stderr)
            return 1

        print(f"\n=== 即将重置以下账号的密码 ===")
        print(f"  用户名: {user.username}")
        print(f"  姓名  : {user.real_name or '(未填)'}")
        print(f"  科室  : {user.department or '(未归口)'}")
        print(f"  角色  : {user.role}")
        print(f"  启用  : {'是' if user.is_active else '否'}")
        print(f"  操作者: {actor.username}（会记入密码审计日志）")
        if user.username == "admin":
            print("\n⚠️ 这是系统管理员账号，拥有全量数据访问权。")
            print("   确认对方确实该拿这个权限再继续。")

        if not args.yes:
            if not sys.stdin.isatty():
                print("\n非交互环境请加 --yes 显式确认。", file=sys.stderr)
                return 2
            ans = input("\n确认重置？输入 yes 继续: ").strip().lower()
            if ans != "yes":
                print("已取消，未做任何修改。")
                return 0

        password = _prompt_password(args.strict)
        svc.reset_password(actor, user.id, password)
        if svc.db is not None:
            svc.db.commit()
        print(f"\n✅ 密码已重置（{len(password)} 位，未打印内容）")
        print(f"   该账号已标记为「登录后强制改密」：用户登录后必须自行设置新密码。")
        print(f"\n现在可以让他用这个密码登录：{args.username}")
        print("登录后系统会立即要求他改成自己的密码。")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
