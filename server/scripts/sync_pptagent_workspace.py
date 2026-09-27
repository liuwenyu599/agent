"""把远程 PPTAgent 产物目录增量镜像到本机。

为什么需要它
------------
PPTAgent 跑在远程服务器上（本机通过 SSH 隧道把 ``127.0.0.1:18061`` 转到远程
``7861``），它的产物落在**远程机器的文件系统**里（默认
``/data/pptagent/workspace/<日期>/<job_id>/``），而本机后端
``PPTAgentClient.scan_progress()`` 是**扫本地目录**的，扫不到远程路径，
于是 ``/api/v1/ppt/jobs/{id}/preview`` 恒返回 0 页 —— 逐页预览永远是灰占位。

本脚本用 SFTP 把远程产物目录**增量镜像到本机**，后端只要把
``PPT_AGENT_WORKSPACE_DIR`` 指向镜像目录，就能正常出逐页预览。
**后端代码无需任何改动**。

为什么不用 rsync / tar over ssh
-------------------------------
两者都在 PPTAgent 的中文路径上实测失败 —— PPTAgent 的预览目录名形如
``.slide_images-pdf-<中文标题>``（名字跟着标题走）：

* ``rsync -av -e ssh ...`` → ``rsync error: error in rsync protocol data
  stream (code 12)``，连接被意外关闭；
* ``ssh ... "tar czf - ." | tar xzf -`` → ``Invalid empty pathname``，
  Git Bash 的 tar 把 UTF-8 路径按 GBK 解，直接乱码。

Python 3 的 str 路径在 Windows 上按 UTF-8 处理、写 NTFS 正常，所以走 SFTP。

时间基准（重要）
----------------
后端按 **文件 mtime** 判断"是不是本次产物"（``since_ts - fresh_tolerance``），
因此镜像必须**保留远程 mtime**。已实测本机与远程服务器时钟同步（误差 <2s），
直接沿用远程 mtime 即可，不需要做偏移校正。

用法
----
::

    # 跑一次（默认读环境变量，见下方 CONFIG）
    python scripts/sync_pptagent_workspace.py

    # 常驻：每 20 秒同步一次（生成过程要能实时看到新出的页）
    python scripts/sync_pptagent_workspace.py --daemon --interval 20

    # 覆盖连接参数
    python scripts/sync_pptagent_workspace.py --host 192.168.68.51 --port 8081 \\
        --user lwy --remote /data/pptagent/workspace --local D:/mirror

环境变量（都可被命令行参数覆盖）::

    PPTAGENT_SYNC_HOST      默认 192.168.68.51
    PPTAGENT_SYNC_PORT      默认 8081
    PPTAGENT_SYNC_USER      默认 lwy
    PPTAGENT_SYNC_REMOTE    默认 /data/pptagent/workspace
    PPTAGENT_SYNC_LOCAL     默认 <server>/data/pptagent_workspace
    PPTAGENT_SYNC_INTERVAL  默认 20（秒，仅 --daemon 生效）
    PPTAGENT_SYNC_PRUNE_DAYS 默认 7（本地镜像保留天数，0 = 不清理）

依赖：``paramiko``（本机 Anaconda Python 已带）。走密钥认证，不处理密码。
"""
from __future__ import annotations

import argparse
import os
import stat
import sys
import time
from pathlib import Path
from typing import Iterable, List, Optional

try:
    import paramiko
except ImportError:  # pragma: no cover - 环境提示
    sys.exit("缺少 paramiko，请先 pip install paramiko")


# ---------------------------------------------------------------- 默认配置

DEFAULT_HOST = os.getenv("PPTAGENT_SYNC_HOST", "192.168.68.51")
DEFAULT_PORT = int(os.getenv("PPTAGENT_SYNC_PORT", "8081"))
DEFAULT_USER = os.getenv("PPTAGENT_SYNC_USER", "lwy")
DEFAULT_REMOTE = os.getenv("PPTAGENT_SYNC_REMOTE", "/data/pptagent/workspace")

_SERVER_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCAL = os.getenv("PPTAGENT_SYNC_LOCAL",
                          str(_SERVER_ROOT / "data" / "pptagent_workspace"))
DEFAULT_INTERVAL = int(os.getenv("PPTAGENT_SYNC_INTERVAL", "20"))
DEFAULT_PRUNE_DAYS = int(os.getenv("PPTAGENT_SYNC_PRUNE_DAYS", "7"))

# 预览无关的大文件不搬，省带宽（PDF/PPTX 动辄几百 KB~MB，预览只需要 jpg/html）
SKIP_SUFFIXES = {".pptx", ".pdf", ".zip"}
SKIP_DIR_NAMES = {".history", "assets"}


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------- 同步主体


class Mirrored:
    """一次同步的统计。"""

    def __init__(self) -> None:
        self.new = 0
        self.updated = 0
        self.skipped = 0
        self.failed = 0

    @property
    def changed(self) -> int:
        return self.new + self.updated

    def __str__(self) -> str:
        return (f"新增 {self.new} / 更新 {self.updated} / "
                f"跳过 {self.skipped} / 失败 {self.failed}")


def _should_skip(name: str, is_dir: bool) -> bool:
    if is_dir:
        return name in SKIP_DIR_NAMES
    return Path(name).suffix.lower() in SKIP_SUFFIXES


def _walk_remote(sftp: "paramiko.SFTPClient", remote_dir: str
                 ) -> Iterable[tuple]:
    """递归列出远程目录下的文件。

    Yields:
        ``(相对路径, 远程绝对路径, SFTPAttributes)``
    """
    stack: List[tuple] = [(remote_dir, "")]
    while stack:
        cur, rel = stack.pop()
        try:
            entries = sftp.listdir_attr(cur)
        except (IOError, OSError) as e:
            log(f"  跳过不可读目录 {rel or '/'}: {e}")
            continue
        for e in entries:
            name = e.filename
            if name in (".", ".."):
                continue
            child_rel = f"{rel}/{name}" if rel else name
            child_abs = f"{cur.rstrip('/')}/{name}"
            if stat.S_ISDIR(e.st_mode or 0):
                if _should_skip(name, True):
                    continue
                stack.append((child_abs, child_rel))
            else:
                if _should_skip(name, False):
                    continue
                yield (child_rel, child_abs, e)


def _needs_update(local_path: Path, attr) -> bool:
    """按 size + mtime 判断是否需要下载（保留 mtime 是后端过滤的前提）。"""
    if not local_path.exists():
        return True
    st = local_path.stat()
    if st.st_size != (attr.st_size or 0):
        return True
    # 容忍 1 秒误差，避免浮点/文件系统精度导致每次都重下
    return abs(st.st_mtime - (attr.st_mtime or 0)) > 1


def sync_once(host: str, port: int, user: str, remote: str,
              local: str, prune_days: int, verbose: bool = False) -> Mirrored:
    m = Mirrored()
    local_root = Path(local)
    local_root.mkdir(parents=True, exist_ok=True)

    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(host, port=port, username=user,
                       allow_agent=True, look_for_keys=True,
                       timeout=20, banner_timeout=20)
        sftp = client.open_sftp()
        try:
            for rel, remote_abs, attr in _walk_remote(sftp, remote):
                dest = local_root / rel
                if not _needs_update(dest, attr):
                    m.skipped += 1
                    continue
                existed = dest.exists()
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_suffix(dest.suffix + ".part")
                try:
                    sftp.get(remote_abs, str(tmp))
                    # 保留远程 mtime：后端靠它判断"是不是本次 job 的产物"
                    os.utime(tmp, (attr.st_mtime or 0, attr.st_mtime or 0))
                    if dest.exists():
                        dest.unlink()
                    tmp.replace(dest)
                    if existed:
                        m.updated += 1
                    else:
                        m.new += 1
                    if verbose:
                        log(f"  ↓ {rel}")
                except (IOError, OSError) as e:
                    m.failed += 1
                    log(f"  ✗ {rel}: {e}")
                    try:
                        if tmp.exists():
                            tmp.unlink()
                    except OSError:
                        pass
        finally:
            sftp.close()
    finally:
        client.close()

    if prune_days > 0:
        _prune_old(local_root, prune_days)
    return m


def _prune_old(local_root: Path, days: int) -> None:
    """清理本地镜像里过期的日期目录（远程目录结构是 <日期>/<job_id>）。"""
    cutoff = time.time() - days * 86400
    for child in local_root.iterdir():
        if not child.is_dir() or not child.name.isdigit() or len(child.name) != 8:
            continue
        try:
            if child.stat().st_mtime < cutoff:
                import shutil
                shutil.rmtree(child, ignore_errors=True)
                log(f"  已清理过期镜像目录 {child.name}")
        except OSError:
            pass


# ---------------------------------------------------------------- 入口


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="把远程 PPTAgent 产物目录增量镜像到本机（供逐页预览扫描）")
    p.add_argument("--host", default=DEFAULT_HOST)
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--user", default=DEFAULT_USER)
    p.add_argument("--remote", default=DEFAULT_REMOTE)
    p.add_argument("--local", default=DEFAULT_LOCAL)
    p.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                   help="--daemon 下的同步间隔（秒）")
    p.add_argument("--prune-days", type=int, default=DEFAULT_PRUNE_DAYS,
                   help="本地镜像保留天数，0 表示不清理")
    p.add_argument("--daemon", action="store_true", help="常驻循环同步")
    p.add_argument("--verbose", action="store_true", help="打印每个下载的文件")
    args = p.parse_args(argv)

    log(f"镜像 {args.user}@{args.host}:{args.port}:{args.remote} -> {args.local}")
    if args.daemon:
        log(f"常驻模式，每 {args.interval}s 同步一次（Ctrl+C 退出）")
        while True:
            try:
                m = sync_once(args.host, args.port, args.user, args.remote,
                              args.local, args.prune_days, args.verbose)
                log(f"同步完成：{m}")
            except KeyboardInterrupt:
                log("已停止")
                return 0
            except Exception as e:  # noqa: BLE001 - 常驻进程不能被单次异常打挂
                log(f"同步失败（{type(e).__name__}）：{e}")
            time.sleep(max(1, args.interval))
    else:
        m = sync_once(args.host, args.port, args.user, args.remote,
                      args.local, args.prune_days, args.verbose)
        log(f"同步完成：{m}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
