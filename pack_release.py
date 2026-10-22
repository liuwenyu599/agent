"""按部署规范打包：git archive HEAD → judicial_app_<SHA>.tar.gz。

与手工 tar 的差别（都是踩过的坑）：
- 用 `git archive HEAD` 而不是打包整个工作区：不会夹带 .env、不会带上未提交的改动。
- 显式排除 server/data、desktop/build、deploy/offline（本地运行产物/离线大文件）。
- 跳过断链符号链接 training/data/raw：`tarfile` 处理 symlink 时 extractfile() 会抛
  KeyError，必须改 member.name 去前缀后 continue，不能让它进包。
- deploy 下入库的 *.sh 缺执行位（git 只记 100644），服务器上要手动补 0755，
  这里在打包阶段就写进 tar 的 mode，避免到服务器再 chmod 一遍。
"""
import io
import subprocess
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parent
EXCLUDE_DIRS = (
    "server/data",
    "desktop/build",
    "deploy/offline",
    "deliverables",  # 本地产物（pptx/html/md），不进生产部署包
)
EXCLUDE_NAMES = {"training/data/raw"}  # 断链符号链接，必须跳过


def main() -> None:
    sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout.strip()
    out = REPO / f"judicial_app_{sha}.tar.gz"

    raw = subprocess.run(
        ["git", "archive", "--format=tar", "HEAD"],
        cwd=REPO, capture_output=True, check=True,
    ).stdout

    kept = skipped = mode_fixed = 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r|") as src, \
            tarfile.open(out, "w:gz") as dst:
        for member in src:
            name = member.name
            # 断链符号链接：改写 name 后跳过，不进包
            if name in EXCLUDE_NAMES or member.issym():
                skipped += 1
                continue
            if any(name == d or name.startswith(d + "/") for d in EXCLUDE_DIRS):
                skipped += 1
                continue
            # 部署脚本补执行位
            if name.startswith("deploy/") and name.endswith(".sh"):
                member.mode = 0o755
                mode_fixed += 1
            dst.addfile(member, src.extractfile(member) if member.isreg() else None)
            kept += 1

    size_mb = out.stat().st_size / 1024 / 1024
    print(f"包名: {out.name}")
    print(f"大小: {size_mb:.1f} MB")
    print(f"条目: 保留 {kept}，跳过 {skipped}，补执行位 {mode_fixed}")


if __name__ == "__main__":
    main()
