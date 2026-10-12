"""账号状态体检：查某个账号是否存在、是否启用、是否待改密，以及候选密码是否匹配。

为什么需要它
------------
反复用登录接口试密码是**最糟糕的排查方式**：`login_rate_limiter` 是进程内单例，
10 分钟内失败 5 次就锁 15 分钟，而且按 **IP + 用户名** 双桶计数——
一旦被锁，界面上只会一直显示「登录尝试过多，请 N 秒后再试」，
把"密码到底对不对"这个真正想验证的信息彻底遮住。

本脚本**直接读库**、用 `verify_password` 校验哈希，
不经过 HTTP、不调用 limiter，因此**不计入失败次数、不会触发锁定**。

在服务器上的用法（容器内）
--------------------------
    cd /opt/justice-office/deploy
    docker compose --env-file .env run --rm migrate python -m scripts.inspect_account admin

    # 一次验多个候选密码（不写进命令行历史）
    docker compose --env-file .env run --rm migrate python -m scripts.inspect_account admin --check

安全约束
--------
- **永不打印明文密码**，只打印候选密码是否匹配（✅/❌）。
- 读取密码候选走 stdin 交互输入，不接受命令行参数，
  避免落进 shell history 与 `ps` 进程列表。
- 只读，不做任何写操作。
"""
from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import select

from app.core.security import verify_password
from app.infrastructure.database import SessionLocal
from app.infrastructure.database.models.identity import UserModel


def _args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="账号状态体检（只读，不触发登录限流）",
    )
    p.add_argument("username", help="要检查的用户名，如 admin")
    p.add_argument("--check", action="store_true",
                   help="交互式验证候选密码是否匹配（密码不会打印、不进命令行历史）")
    p.add_argument("--list", action="store_true",
                   help="列出全部账号的概要（不含任何哈希或密码）")
    return p.parse_args()


def _show(db, m: UserModel) -> None:
    """打印单个账号的状态。不打印哈希——即使它也算敏感信息。"""
    print()
    print(f"  用户名      : {m.username}")
    print(f"  邮箱        : {m.email}")
    print(f"  姓名        : {m.real_name or '(未填)'}")
    print(f"  科室        : {m.department or '(未归口)'}"
          f"{f'  code={m.department_code}' if m.department_code else ''}")
    print(f"  角色        : {m.role}")
    print(f"  是否启用    : {'✅ 是' if m.is_active else '❌ 否（账号已停用，登录会返回 403）'}")
    print(f"  待改密      : {'⚠️  是（登录后强制改密）' if m.must_change_password else '否'}")
    print(f"  创建时间    : {m.created_at}")
    print(f"  更新时间    : {m.updated_at}")

    # 哈希格式看一眼即可判断是否被外部工具改过（例如 pgcrypto 的非 bcrypt 格式）
    hashed = m.hashed_password or ""
    algo = "bcrypt" if hashed.startswith(("$2a$", "$2b$", "$2y$")) else "⚠️ 非 bcrypt 格式"
    print(f"  密码哈希    : {algo}（长度 {len(hashed)}）")


def _check_passwords(db, username: str) -> None:
    """交互式校验候选密码。

    逐个比对**已存的同一个哈希**，所以匹配与否直接反映真实登录结果
    （登录接口的判定就是 `verify_password(输入, user.hashed_password)`）。
    """
    m = db.scalar(select(UserModel).where(UserModel.username == username))
    if not m:
        print(f"账号 {username} 不存在，无法校验密码。", file=sys.stderr)
        return
    print(f"\n正在校验 {username} 的候选密码（输入不回显，密码不会被打印）")
    print("至少输入一个候选，回车两次结束：")
    tried = 0
    matched = None
    while True:
        try:
            pw = getpass.getpass(f"  候选密码 #{tried + 1}: ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not pw:
            break
        if verify_password(pw, m.hashed_password):
            matched = pw
            print(f"  ✅ 匹配成功（第 {tried + 1} 个候选）")
        else:
            print(f"  ❌ 不匹配（第 {tried + 1} 个候选）")
        tried += 1
    print()
    if matched:
        print(f"结论：{username} 的密码就是上面标记 ✅ 的那个。")
        if m.must_change_password:
            print("      该账号标记为待改密，用户登录后会被强制改密。")
    else:
        print(f"结论：{tried} 个候选都不匹配，密码不是这些之一。")
        print("      用「用户管理 → 重置密码」设一个新的，别再靠猜——")
        print("      每次猜错都在给 IP 桶计数，很快会锁 15 分钟。")
        print()
        print("      ⚠ 注意：开发机上的这个库和生产库（10.128.85.133）**不是同一个**，")
        print("        密码未必相同。以本脚本在**服务器上**跑出来的结果为准。")


def main() -> int:
    args = _args()
    db = SessionLocal()
    try:
        if args.list:
            rows = db.scalars(select(UserModel).order_by(UserModel.created_at)).all()
            print(f"\n共 {len(rows)} 个账号：\n")
            print(f"  {'用户名':<18}{'角色':<16}{'科室':<14}{'启用':<6}待改密")
            print("  " + "-" * 66)
            for m in rows:
                print(f"  {m.username:<18}{m.role:<16}"
                      f"{(m.department or '-')[:12]:<14}"
                      f"{'✓' if m.is_active else '✗':<6}"
                      f"{'⚠' if m.must_change_password else '-'}")
            print()
            return 0

        m = db.scalar(select(UserModel).where(UserModel.username == args.username))
        if not m:
            print(f"\n❌ 账号 {args.username} 在库里不存在。")
            print("\n库里现有哪些账号，跑这个看全貌：")
            print(f"  python -m scripts.inspect_account <用户名> --list\n")
            # 顺手列一下，便于直接看到正确拼写
            rows = db.scalars(select(UserModel)).all()
            if rows:
                print("现存账号：" + "、".join(x.username for x in rows))
            return 1

        print(f"\n=== 账号体检：{args.username} ===")
        _show(db, m)
        if args.check:
            _check_passwords(db, args.username)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
