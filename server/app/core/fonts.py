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

## 为什么是 Noto Sans CJK SC

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

模板的 `font` 字段仍可由用户在「模板中心」按需覆盖为仿宋/宋体等。
"""

# 写进 pptx 的字体名，由后端容器与客户端的字体环境共同解析。
DEFAULT_CJK_FONT = "Noto Sans CJK SC"

# 模板 font 字段的建议选项（按国产化环境的可用性排序）
SUGGESTED_CJK_FONTS = (
    "Noto Sans CJK SC",   # 后端已装、国产 OS 标配（默认）
    "WenQuanYi Micro Hei",  # 国产 OS 常见
    "Source Han Sans SC",   # 思源黑体，部分版本预装
    "FangSong_GB2312",      # 仿宋，公文常用（需目标机装有）
    "SimSun",               # 宋体，仅 Windows
)
