"""把 jpackage 产出的 deb 重打包成「对外可见名称全中文」的交付包。

为什么需要它
------------
jpackage 有三处名称，且**不能都改成中文**：

| 位置 | 来源 | 能否中文 |
|---|---|---|
| `Package:` 字段 | `linux.packageName` | ❌ **dpkg 强制小写 ASCII**，写了中文 dpkg 直接拒绝安装 |
| `/opt/<目录>` | 同上（`--linux-package-name`） | ✅ 可改（本脚本做） |
| `.desktop` 的 `Name=` | 顶层 `packageName` | ✅ 可改（本脚本做） |

顶层 `packageName` 必须是 ASCII，因为它同时决定 `bin/YunFaZhiBan` 这个**可执行文件名**
（jpackage 限制）。所以「菜单里显示中文」这件事 jpackage 的 DSL 做不到，
只能在打包后改包内文件——这就是本脚本存在的原因。

已核实的安全性（改动前必须确认，��则会出现「装得上、启动不了」）
----------------------------------------------------------------
- 启动器 ELF **不含** `/opt/yunfazhiban` 字面量：它用 `dirname /proc/self/exe`
  定位自身所在目录，再 `dpkg -L <Package名>` 找 `../lib/libapplauncher.so`。
  因为 `Package:` 保持 ASCII 不变，`dpkg -L` 仍能正常工作。
- app jar 内`yunfazhiban` 出现 0 次；全包只有 `.desktop` 与 `postinst/prerm`
  引用了安装路径，本脚本全部同步改掉。
- 无符号链接、无硬链接、无 `/usr/bin` 入口需要跟随。

用法
----
    python tools/repack_deb_cn.py <输入deb> <输出deb>
"""
import gzip
import io
import sys
import tarfile
import time
import zstandard

# 内部包名/ 目录名 → 对外中文名
OLD_PKG = "yunfazhiban"
NEW_PKG_CN = "白云司法局智慧办公平台"
OLD_APP = "YunFaZhiBan"          # 顶层 packageName（exe 名，保持不变）
OLD_DIR = f"/opt/{OLD_PKG}"
NEW_DIR = f"/opt/{NEW_PKG_CN}"
OLD_DESKTOP = f"{OLD_PKG}-{OLD_APP}.desktop"


def ar_header(name: str, size: int) -> bytes:
    """构造 ar 成员头（60 字节定长字段）。

    ⚠ 字段偏移是**定长**的，不能对拼接结果做 rstrip/strip——那会破坏后面的
    size 字段偏移（首轮就这么把 size 解析成了垃圾）。
    """
    h = name.ljust(16)[:16]
    h += time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(0)).ljust(12)[:12]
    h += "0".ljust(6)[:6]          # uid
    h += "0".ljust(6)[:6]          # gid
    h += "100644".ljust(8)[:8]     # mode
    h += str(size).ljust(10)[:10]  # size
    h += "\x60\n"                  # 结尾magic
    return h.encode("ascii")


def read_ar(raw: bytes):
    """解析 ar归档，返回 [(name, header60, data)]。"""
    assert raw[:8] == b"!<arch>\n", "不是有效的 deb（ar 魔数错误）"
    members, off = [], 8
    while off + 60 <= len(raw):
        hdr = raw[off:off + 60]
        name = hdr[0:16].decode("ascii").strip().rstrip("/")
        try:
            size = int(hdr[48:58].decode("ascii").strip())
        except ValueError:
            break
        members.append((name, hdr, raw[off + 60:off + 60 + size]))
        off += 60 + size + (size % 2)
    return members


def rewrite_control(data: bytes) -> bytes:
    """改 control.tar.zst 里的 ./control 与四个维护脚本。"""
    plain = zstandard.ZstdDecompressor().decompress(data)
    src = tarfile.open(fileobj=io.BytesIO(plain))

    out = io.BytesIO()
    # ⚠️ 必须显式 format=GNU_FORMAT，不能用默认的 PAX。
    # PAX 会为每个条目写一个 `x` 类型的扩展头（././@PaxHeader），
    # 而老版本 dpkg-deb（麒麟 V10 / Ubuntu 18.04 基线）不认这种头，
    # 报「不支持的 PAX tar 头部类型 'x'」并带连「断开的管道」，
    # 表现为「软件包无法安装或移除」。jpackage 原生产出用的是 GNU 格式。
    with tarfile.open(fileobj=out, mode="w",
                      format=tarfile.GNU_FORMAT) as dst:
        for member in src.getmembers():
            payload = src.extractfile(member).read() if member.isreg() else None
            if member.name == "./control":
                text = payload.decode("utf-8")
                before = text
                # 包名保持 ASCII（dpkg 强制）；描述里的机构名对齐首页（去掉「区」）
                text = text.replace(
                    "Description: 白云区司法局智慧办公平台",
                    f"Description: {NEW_PKG_CN}",
                )
                # 麒麟 V10 基于 Ubuntu 18/20，没有 t64 后缀包名
                text = text.replace("libpng16-16t64", "libpng16-16")
                print(f"  control: {'有改动' if text != before else '无改动'}")
                payload = text.encode("utf-8")
                member.size = len(payload)
            elif member.name in ("./postinst", "./prerm", "./preinst", "./postrm"):
                text = payload.decode("utf-8")
                # jpackage 实际写入的是 {OLD_DIR}/lib/{OLD_PKG}-{OLD_APP}.desktop
                # ——中间有 lib/ 一层。早期版本按 {OLD_DIR}/{...} 匹配，静默匹配 0 处，
                # 结果「改名条目 +N、postinst 却没动」，装完应用菜单里不出现图标。
                old_ref = f"{OLD_DIR}/lib/{OLD_PKG}-{OLD_APP}.desktop"
                new_ref = f"{NEW_DIR}/lib/{OLD_PKG}-{OLD_APP}.desktop"
                n = text.count(old_ref)
                if n:
                    text = text.replace(old_ref, new_ref)
                    print(f"  {member.name}: 修正 {n} 处安装路径")
                else:
                    # 兜底：只要出现旧目录就整体替换，并明确告警
                    n2 = text.count(OLD_DIR)
                    if n2:
                        text = text.replace(OLD_DIR, NEW_DIR)
                        print(f"  {member.name}: ⚠ 未匹配预期引用，"
                              f"按目录前缀兜底替换 {n2} 处")
                payload = text.encode("utf-8")
                member.size = len(payload)
            dst.addfile(member, io.BytesIO(payload) if payload is not None else None)

    # **必须用 gzip 而非 zstd**：dpkg < 1.21.18（麒麟 V10 / Ubuntu 18.04 基线）
    # 不认 zstd 压缩的 tar 成员，会报「不支持的 PAX tar 头部类型 'x'」
    # 且报「断开的管道」，与包内容无关，纯粹是压缩格式不兼容。
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode='wb', compresslevel=6, mtime=0) as gz:
        gz.write(out.getvalue())
    return buf.getvalue()


def rewrite_data(data: bytes) -> bytes:
    """改 data.tar.zst：整体重命名 /opt/yunfazhiban → /opt/白云司法局智慧办公平台，
    并重写 .desktop 的 Name/Exec/Icon。"""
    plain = zstandard.ZstdDecompressor().stream_reader(io.BytesIO(data)).read()
    src = tarfile.open(fileobj=io.BytesIO(plain))

    renamed = desktop_fixed = 0
    out = io.BytesIO()
    # ⚠️ 必须显式 format=GNU_FORMAT，不能用默认的 PAX。
    # PAX 会为每个条目写一个 `x` 类型的扩展头（././@PaxHeader），
    # 而老版本 dpkg-deb（麒麟 V10 / Ubuntu 18.04 基线）不认这种头，
    # 报「不支持的 PAX tar 头部类型 'x'」并带连「断开的管道」，
    # 表现为「软件包无法安装或移除」。jpackage 原生产出用的是 GNU 格式。
    with tarfile.open(fileobj=out, mode="w",
                      format=tarfile.GNU_FORMAT) as dst:
        for member in src.getmembers():
            name = member.name
            # 目录前缀改名（含 .desktop 文件名本身）
            if name.startswith(f".{OLD_DIR}/") or name == f".{OLD_DIR}":
                member.name = name.replace(f".{OLD_DIR}", f".{NEW_DIR}", 1)
                renamed += 1
            # 启动器与 .desktop 文件名保持原样（jpackage 内部标识，改了会与
            # Package 名脱节；且它是 dpkg -L 的匹配依据）
            if member.name.endswith(f"/{OLD_DESKTOP}"):
                payload = src.extractfile(member).read().decode("utf-8")
                before = payload
                payload = payload.replace(f"Name={OLD_APP}", f"Name={NEW_PKG_CN}")
                # Comment 是 jpackage 从顶层 description 带下来的，仍带「区」字，
                # 与 Name 和界面标题（白云司法局智慧办公平台）不一致，一并对齐。
                payload = payload.replace("Comment=白云区司法局智慧办公平台",
                                          f"Comment={NEW_PKG_CN}")
                payload = payload.replace(OLD_DIR, NEW_DIR)
                if payload != before:
                    desktop_fixed += 1
                # 自检：这两条任一不成立就说明替换没生效，直接失败。
                # 「改名条目 +N 但.desktop 没改」这种静默半成功最难查——
                # 包能装、能启动，只是菜单里名字还是英文。
                assert f"Name={NEW_PKG_CN}" in payload, ".desktop 的 Name 未改成中文"
                assert NEW_DIR in payload, ".desktop 的 Exec/Icon 仍指向旧目录"
                assert OLD_DIR not in payload, ".desktop 仍残留旧安装目录"
                member.size = len(payload.encode("utf-8"))
                dst.addfile(member, io.BytesIO(payload.encode("utf-8")))
                continue
            dst.addfile(member,
                        src.extractfile(member) if member.isreg() else None)

    print(f"  改名条目: {renamed}  .desktop 重写: {desktop_fixed}")
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode='wb', compresslevel=6, mtime=0) as gz:
        gz.write(out.getvalue())
    return buf.getvalue()


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    src_path, dst_path = sys.argv[1], sys.argv[2]
    raw = open(src_path, "rb").read()
    members = read_ar(raw)

    out = [b"!<arch>\n"]
    for name, hdr, data in members:
        if name.startswith("control.tar"):
            print("control.tar.zst -> control.tar.gz:")
            new = rewrite_control(data)
            print(f"  {len(data):,} -> {len(new):,} 字节")
            out.append(ar_header("control.tar.gz", len(new)))
            out.append(new)
        elif name.startswith("data.tar"):
            print("data.tar.zst -> data.tar.gz:（需重新压缩，104MB 约 2–4 分钟）")
            new = rewrite_data(data)
            print(f"  {len(data):,} -> {len(new):,} 字节")
            out.append(ar_header("data.tar.gz", len(new)))
            out.append(new)
        else:
            out.append(hdr)
            out.append(data)
        if len(out[-1]) % 2:
            out.append(b"\n")

    open(dst_path, "wb").write(b"".join(out))
    verify(dst_path)
    print(f"\n完成: {dst_path}")
    print(f"  压缩格式: gzip —— 老 dpkg 不认 zstd")
    print(f"  tar 格式 : GNU（无 PAX 扩展头）—— 老 dpkg-deb 会拒x 类型头")
    print(f"  Package 保持 ASCII: {OLD_PKG}（dpkg 强制，不可中文）")
    print(f"  安装目录: {NEW_DIR}")
    print(f"  菜单显示名: {NEW_PKG_CN}")


def verify(path: str) -> None:
    """产物自检：把「装不上」的两个已知成因挡在交付之前。

    这两项都是**装得上但完全看不出问题**的类型——包能传过去、能双击、
    dpkg 才在解压阶段失败。靠人工看日志发现得太晚，所以写进脚本。
    """
    raw = open(path, "rb").read()
    if raw[:8] != b"!<arch>\n":
        raise SystemExit("自检失败：不是合法的 ar 归档")
    off = 8
    members = {}
    while off + 60 <= len(raw):
        hdr = raw[off:off + 60]
        name = hdr[0:16].decode("ascii").strip().rstrip("/")
        try:
            size = int(hdr[48:58].decode("ascii").strip())
        except ValueError:
            break
        members[name] = (off + 60, size)
        off += 60 + size + (size % 2)
    if off != len(raw):
        raise SystemExit(f"自检失败：归档长度不符（累计 {off} vs 实际 {len(raw)}）")

    leftover = [n for n in members if n.endswith(".zst")]
    if leftover:
        raise SystemExit(f"自检失败：残留 zstd 成员 {leftover}，老 dpkg 无法解压")

    for name in ("control.tar.gz", "data.tar.gz"):
        if name not in members:
            raise SystemExit(f"自检失败：缺少 {name}")
        blob = raw[members[name][0]:members[name][0] + members[name][1]]
        if blob[:2] != b"\x1f\x8b":
            raise SystemExit(f"自检失败：{name} 魔数不是 gzip（1f 8b），实际 {blob[:2]!r}")
        plain = gzip.decompress(blob)
        # 用tarfile 解析真实条目，而不是逐512字节扫 typeflag——
        # 后者会把 ELF/jar 等二进制内容里恰好等于 b'x'/b'g' 的字节误判成扩展头。
        with tarfile.open(fileobj=io.BytesIO(plain)) as tf:
            bad = [x.name for x in tf.getmembers() if x.type in ("x", "g")]
        if bad:
            raise SystemExit(
                f"自检失败：{name} 含 PAX/GNU 扩展头 {bad[:3]}，"
                f"老版本 dpkg-deb 会报「不支持的 PAX tar 头部类型 'x'」"
            )
    print("  [自检] ar 结构 OK | gzip 魔数 OK | 无 .zst |无 PAX/GNU 扩展头")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())