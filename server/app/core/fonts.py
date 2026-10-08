"""PPT 中文字体默认值。

## 为什么不能硬编码「微软雅黑」

pptx 里的字体名最终由**打开它的软件**（PowerPoint / WPS）解析，服务端容器
本身有没有这个字体并不影响客户端显示。所以真正需要满足的是：

  · Windows 客户端（Office / WPS）——有 微软雅黑、SimHei
  · 麒麟客户端（WPS）——**没有微软雅黑**，但有 SimHei（黑体，WPS 自带）

原先 11 处硬编码「微软雅黑」，在麒麟 + 麒麟版 WPS 上会触发字体回退，
公文观感走样。这里统一改为 SimHei（黑体）：两个平台的WPS 都自带，
且同为中文黑体，观感与雅黑接近。

## 为什么不做运行时探测

探测系统可用字体（fc-list）需要每个 worker 进程跑一次外部命令，
而这里的取值只是**写进 pptx 的字符串**，最终由客户端解析——
服务端探测出来的名字对客户端没有意义，反而引入缓存与超时复杂度。
模板的 `font` 字段仍可由用户在「模板中心」里按需覆盖。
"""

# 中文字体默认值。写进 pptx 后由客户端的 WPS/Office 解析并回退。
DEFAULT_CJK_FONT = "SimHei"

# 供文档/前端展示用的可选字体（模板 font 字段的下拉建议）
SUGGESTED_CJK_FONTS = (
    "SimHei",           # 黑体，Windows/麒麟 WPS 均有
    "Microsoft YaHei",  # 微软雅黑，仅 Windows
    "Noto Sans CJK SC",  # 思源黑体，Linux 常见
    "FangSong_GB2312",  # 仿宋，公文常用
    "SimSun",           # 宋体
)
