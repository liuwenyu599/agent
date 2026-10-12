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

# ── freedesktop 标准目录（菜单图标能不能出现，全看有没有这两个目录的条目）──
# jpackage 把 .desktop 放在 {NEW_DIR}/lib/ 下，那**不是任何桌面会去扫的目录**，
# 再靠 `xdg-desktop-menu install <绝对路径>` 去补——该命令期望的是已在
# applications 目录里的 desktop 文件 id，给绝对路径多半找不到、返回非 0，
# 而 postinst 开头是 `set -e` → 整个安装报「Error processing triggers」。
# 现象就是用户说的：装完了，但应用菜单「办公」里压根找不到图标。
# 正解是直接放进标准目录，不依赖任何工具的运行时行为。
STD_APPS_DIR = "./usr/share/applications"
STD_ICON_DIR = "./usr/share/icons/hicolor/256x256/apps"
STD_DESKTOP_NAME = f"{OLD_PKG}.desktop"          # 标准目录里的文件名（纯 ASCII，稳）
STD_ICON_NAME = f"{OLD_PKG}.png"


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


def _new_maint_script(which: str) -> str:
    """重写 jpackage 的四个维护脚本。

    为什么必须自己写、不能沿用 jpackage 的：
    jpackage 的 postinst 只有一句 `xdg-desktop-menu install <绝对路径>`。
    而 `xdg-desktop-menu install` 期望的是**已经位于 applications 目录里**的
    desktop 文件 id，给它 /opt/... 下的绝对路径基本找不到、返回非 0；
    又因为脚本开头是 `set -e`，这一步失败会把整个安装打成
    「Error processing triggers ... returned error exit status 1」。
    桌面菜单图标也已经由 data.tar 里的标准目录条目负责（不依赖任何命令），
    所以这里只做「桌面图标 + 菜单缓存刷新」，且全部 `|| true` 兜底。
    """
    head = (
        "#!/bin/sh\n"
        "# 由 repack_deb_cn.py 重写：图标与桌面快捷方式全部自带，不依赖 xdg-desktop-menu\n"
        "set -e\n"
        '\nAPPS="/usr/share/applications"\n'
        f'export DESKTOP_SRC="{NEW_DIR}/lib/{OLD_PKG}-{OLD_APP}.desktop"\n'
        'export DESKTOP_ICON_NAME="' + STD_DESKTOP_NAME + '"\n'
        'TARGET_USER="${SUDO_USER:-}"\n'
        "\n"
        "# 用 env 变量而不是把路径内插进命令串：内插会在 root 侧就展开 $HOME，\n"
        "# 图标会建到 /root 而不是当前登录用户的桌面。\n"
        "make_desktop_icons() {\n"
        '  [ -f "$DESKTOP_SRC" ] || return 0\n'
        '  [ -n "$TARGET_USER" ] || return 0\n'
        "  for d in Desktop 桌面; do\n"
        '    su -s /bin/sh -c \'mkdir -p "$HOME/$d" && cp "$DESKTOP_SRC" '
        '"$HOME/$d/$DESKTOP_ICON_NAME" && chmod +x "$HOME/$d/$DESKTOP_ICON_NAME"\' \\\n'
        '      "$TARGET_USER" 2>/dev/null || true\n'
        "  done\n"
        "}\n"
        "\n"
        'refresh_menu_cache() {\n'
        '  command -v update-desktop-database >/dev/null 2>&1 '
        '&& update-desktop-database "$APPS" || true\n'
        "}\n"
        "\n"
    )
    if which == "./postinst":
        body = (
            'case "$1" in\n'
            "  configure)\n"
            "    make_desktop_icons\n"
            "    refresh_menu_cache\n"
            "    ;;\n"
            "  abort-upgrade|abort-remove|abort-deconfigure)\n"
            "    ;;\n"
            "  *)\n"
            "    exit 0\n"
            "    ;;\n"
            "esac\n"
        )
    elif which == "./prerm":
        body = (
            'case "$1" in\n'
            "  remove|deconfigure)\n"
            '    [ -n "$TARGET_USER" ] || exit 0\n'
            "    for d in Desktop 桌面; do\n"
            '      su -s /bin/sh -c \'rm -f "$HOME/$d/$DESKTOP_ICON_NAME"\' \\\n'
            '        "$TARGET_USER" 2>/dev/null || true\n'
            "    done\n"
            '    rm -f "$APPS/$DESKTOP_ICON_NAME" || true\n'
            "    ;;\n"
            "  upgrade|failed-upgrade)\n"
            "    ;;\n"
            "  *)\n"
            "    exit 0\n"
            "    ;;\n"
            "esac\n"
        )
    else:  # preinst / postrm：无需动作
        body = 'exit 0\n'
    return head + body + "\nexit 0\n"


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
                # 整段重写，不再沿用 jpackage 的 xdg-desktop-menu 方案
                payload = _new_maint_script(member.name).encode("utf-8")
                member.size = len(payload)
                print(f"  {member.name}: 重写（桌面图标 + 菜单刷新，不依赖外部命令）")
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
    desktop_payload = None      # .desktop 的最终内容，用于复制到标准目录
    icon_payload = None         # 图标 png 的内容
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
                desktop_payload = payload.encode("utf-8")
                dst.addfile(member, io.BytesIO(desktop_payload))
                continue
            # 抓图标本体（只读一次，后面要复制进 hicolor 标准目录）
            if member.name.endswith("/lib/YunFaZhiBan.png") and member.isreg():
                icon_payload = src.extractfile(member).read()
            dst.addfile(member,
                        src.extractfile(member) if member.isreg() else None)

        assert desktop_payload, "包里没找到 .desktop，无法装进标准目录"
        assert icon_payload, "包里没找到图标 png"

        # ── 追加 freedesktop 标准目录条目：菜单图标靠它们自动出现 ──
        # 必须在 with tarfile.open(...) **内部**写：出了 with，dst 已关闭，
        # 再 addfile 会抛 "TarFile is closed"。
        for d in ("./usr", "./usr/share", STD_APPS_DIR,
                  "./usr/share/icons", "./usr/share/icons/hicolor",
                  "./usr/share/icons/hicolor/256x256", STD_ICON_DIR):
            di = tarfile.TarInfo(d)
            di.type = tarfile.DIRTYPE
            di.mode = 0o755
            di.mtime = 0
            dst.addfile(di)

        fi = tarfile.TarInfo(f"{STD_APPS_DIR}/{STD_DESKTOP_NAME}")
        fi.size = len(desktop_payload)
        fi.mode = 0o644
        fi.mtime = 0
        dst.addfile(fi, io.BytesIO(desktop_payload))

        gi = tarfile.TarInfo(f"{STD_ICON_DIR}/{STD_ICON_NAME}")
        gi.size = len(icon_payload)
        gi.mode = 0o644
        gi.mtime = 0
        dst.addfile(gi, io.BytesIO(icon_payload))

    print(f"  改名条目: {renamed}  .desktop 重写: {desktop_fixed}")
    print(f"  已追加标准菜单条目: {STD_APPS_DIR}/{STD_DESKTOP_NAME}"
          f" + {STD_ICON_DIR}/{STD_ICON_NAME}")
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
    _verify_shortcut(raw, members)
    return 0


def _verify_shortcut(raw: bytes, members: dict) -> None:
    """自检：菜单图标 / 桌面快捷方式是否真的具备。

    「装完了但菜单里没有图标」是**零报错**故障——安装全程 exit 0，
    用户只看到菜单里没东西，只能靠真人反馈。所以必须在这里挡掉。
    """
    plain = gzip.decompress(
        raw[members["data.tar.gz"][0]:members["data.tar.gz"][0] + members["data.tar.gz"][1]])
    with tarfile.open(fileobj=io.BytesIO(plain)) as tf:
        names = {m.name for m in tf.getmembers()}
        std_desktop = f"{STD_APPS_DIR}/{STD_DESKTOP_NAME}"
        std_icon = f"{STD_ICON_DIR}/{STD_ICON_NAME}"
        problems = []
        if std_desktop not in names:
            problems.append(f"缺 {std_desktop}（菜单图标不会出现）")
        if std_icon not in names:
            problems.append(f"缺 {std_icon}（菜单图标会是空白）")
        if any(m.startswith("./usr") and not m.startswith(f"{STD_APPS_DIR}/")
               and not m.startswith(f"{STD_ICON_DIR}/") for m in names):
            pass
        if std_desktop in names:
            txt = tf.extractfile(std_desktop).read().decode("utf-8")
            if f"Name={NEW_PKG_CN}" not in txt:
                problems.append("标准目录里的 .desktop 名称不是中文")
            if NEW_DIR not in txt:
                problems.append("标准目录里的 .desktop Exec/Icon 路径不对")
        # postinst 不能再依赖 xdg-desktop-menu
        # ⚠ 只看**命令行调用**，不能全文搜字符串：重写后的脚本注释里
        # 写着「不依赖 xdg-desktop-menu」，全文匹配会把自己判为不合格。
        cplain = gzip.decompress(
            raw[members["control.tar.gz"][0]:members["control.tar.gz"][0] + members["control.tar.gz"][1]])
        with tarfile.open(fileobj=io.BytesIO(cplain)) as ctf:
            post = ctf.extractfile("./postinst").read().decode("utf-8")
        code = [ln.strip() for ln in post.splitlines()
                if ln.strip() and not ln.strip().startswith("#")]
        if any("xdg-desktop-menu" in ln for ln in code):
            problems.append("postinst 仍执行 xdg-desktop-menu（安装会报 triggers 错误）")
        if "make_desktop_icons" not in post:
            problems.append("postinst 没有建桌面图标")
    if problems:
        raise SystemExit("自检失败：\n  - " + "\n  - ".join(problems))
    print(f"  [自检] 菜单条目 {STD_DESKTOP_NAME} + 图标 + 桌面快捷方式 全部就位")


if __name__ == "__main__":
    raise SystemExit(main())