"""PPT 中文字体默认值。

## 字体名写进 pptx 后由谁解析

必须先分清三条链路，否则很容易改错方向：

1. **工作台预览（主场景）** —— 后端 `PPTService.preview_document` 用
   `soffice --headless --convert-to pdf` 再 `pdftoppm -png` 逐页转图，
   客户端只看 PNG，**从不打开 pptx**。渲染发生在 `justice-api` 容器内，
   所以**只要该容器装了字体就够，与客户端机器无关**。
2. **导出 pptx 给用户自行打开** —— 字体由用户机器的 WPS/Office 解析，
   缺字体会回退到系统中文字体，观感可能变化但不影响可用性。
3. **后端容器自己的字体** —— `deploy/Dockerfile` 第 29 行只装了
   `fonts-noto-cjk`（注释即写明「LibreOffice 转换时中文字体渲染」），
   **没有 SimHei / 微软雅黑**。

## 中文为什么是 Noto Sans CJK SC

必须**后端与国产客户端都有**，逐个排除：

| 字体 | Windows | 麒麟/统信 | 后端容器 |
|---|---|---|---|
| 微软雅黑 | 有 | **无** | **无** |
| SimHei | 有 | 通常无 | **无**（Linux 无此商业字体） |
| SimSun | 有 | 无 | 无 |
| **Noto Sans CJK SC** | 需另装 | **标配** | **已装**（fonts-noto-cjk） |

结论：`Noto Sans CJK SC` 是唯一同时覆盖「后端渲染」与「国产客户端」的选项。
Windows 侧未装时会回退到系统中文字体——但预览走第 1 条链路（后端渲染），
Windows 客户端看到的同样是后端渲好的 PNG，故回退影响面很小。

## 西文为什么单独走 Times New Roman

`Noto Sans CJK SC` 在 Windows 上**不是预装字体**，用户把 pptx 下载到本地用
PowerPoint/WPS 打开时匹配不到这个名字，整行会一起回退——中文落到宋体、数字
落到 Calibri，「系统上（后端渲染的预览）正常、下载下来不正常」就是这么来的
（用户 2026-11-09 反馈）。

`Times New Roman` 是 Windows / Office / WPS 全平台自带，政务文稿里衬线数字
也比无衬线更端正，所以西文（数字、英文）与中文分开写：`<a:latin>` 用
`DEFAULT_LATIN_FONT`，`<a:ea>`/`<a:cs>` 用 `DEFAULT_CJK_FONT`。斜体一律清掉，
不做「斜体衬线数字」。容器另有 `fonts-liberation` 提供 Times 的度量兼容替代
（LibreOffice 会自动把 Times New Roman 映射到 Liberation Serif），保证预览与
下载后的行宽一致。
"""

import os

# 写进 pptx 的中文字体名，由后端容器与客户端的中文环境共同解析。
DEFAULT_CJK_FONT = os.getenv("PPT_CJK_FONT", "").strip() or "Noto Sans CJK SC"

# 写进 pptx 的西文/数字字体名。Times New Roman 是全平台自带，且不随容器变化。
DEFAULT_LATIN_FONT = os.getenv("PPT_LATIN_FONT", "").strip() or "Times New Roman"

# 模板 font 字段的建议选项（按国产化环境的可用性排序）
SUGGESTED_CJK_FONTS = (
    "Noto Sans CJK SC",   # 后端已装、国产 OS 标配（默认）
    "WenQuanYi Micro Hei",  # 国产 OS 常见
    "Source Han Sans SC",   # 思源黑体，部分版本预装
    "FangSong_GB2312",      # 仿宋，公文常用（需目标机装有）
    "SimSun",               # 宋体，仅 Windows
)

# 模板主题里常见的西文/衬线字体名。模板自带的字体只反映原设计者的示例排法，
# 不是本系统的字体约定：照抄会把「斜体 Times 数字 + 宋体中文」带进成稿。
# 无衬线黑体系才允许继承，其余统一回退到公文字体。
_NEUTRAL_CJK_FONT_KEYS = (
    "noto sans cjk", "source han sans", "思源黑体", "黑体", "simhei",
    "wenquanyi", "文泉驿", "microsoft yahei", "微软雅黑",
    "harmonyos sans", "dengxian", "等线", "heiti",
)


def normalize_theme_font(value: str | None) -> str:
    """模板主题解析出的字体：只认无衬线黑体系，其余（Arial/Times/宋体等）回落。

    用户在「模板中心」显式设置的仿宋/楷体等公文字体走另一条链路，不经过这里，
    因此不会被归一掉。
    """
    name = str(value or "").strip()
    if not name or name.startswith("+"):  # +mj-lt / +mn-ea 是主题占位符
        return DEFAULT_CJK_FONT
    lowered = name.lower()
    if any(key in lowered for key in _NEUTRAL_CJK_FONT_KEYS):
        return name
    return DEFAULT_CJK_FONT


def apply_cjk_font(run, font: str = DEFAULT_CJK_FONT,
                   latin: str = DEFAULT_LATIN_FONT) -> None:
    """把一个 run 的西文 / 中文 / 复杂文种字体分别写定，并清除模板遗留的斜体。

    只设 ``run.font.name`` 写的是 ``<a:latin>``：中文仍按 ``<a:ea>`` 继承模板
    主题（常见宋体），数字用外文字体，混合排版就会出现「中文宋体 + 斜体衬线
    数字」。这里三种文种都显式写死——西文/数字用 ``latin``（默认 Times New
    Roman，Windows 自带），中文/东亚用 ``font``，复杂文种跟中文；同时显式
    关掉 ``i``（斜体）。
    """
    from pptx.oxml.ns import qn

    name = str(font or DEFAULT_CJK_FONT).strip() or DEFAULT_CJK_FONT
    latin_name = str(latin or DEFAULT_LATIN_FONT).strip() or DEFAULT_LATIN_FONT
    run.font.name = latin_name
    r_pr = run._r.get_or_add_rPr()
    _TAIL = ("a:sym", "a:hlinkClick", "a:hlinkMouseOver", "a:rtl", "a:extLst")
    for tag, successors in (("a:ea", ("a:cs",) + _TAIL), ("a:cs", _TAIL)):
        node = r_pr.find(qn(tag))
        if node is None:
            node = r_pr.makeelement(qn(tag), {})
            r_pr.insert_element_before(node, *successors)
        node.set("typeface", name)
    if r_pr.get("i") not in (None, "0", "false"):
        r_pr.set("i", "0")
