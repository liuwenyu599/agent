package com.judicialai.desktop.design.theme

import androidx.compose.ui.graphics.Color

/**
 * 调色板：统一取自司法局政务前端设计稿（浅色政务风）。
 *
 * 约定：
 * 1. 页面内禁止自造色值，一律引用本文件；
 * 2. 文件下半部分的「兼容别名」仅供历史代码引用，新代码请使用设计稿语义色名；
 * 3. 主色为政务蓝 #1f3a5f，强调色为司法红 #b4231a（红头 / 徽标 / 关键操作）。
 */

// ---- 布局骨架 ----
val AppBg = Color(0xFFEEF1F6)        // --bg 应用底色
val Surface = Color(0xFFFFFFFF)      // --surface 卡片/面板
val SurfaceSoft = Color(0xFFF7F9FC)  // 次级面板（会话栏、页面底）
val Line = Color(0xFFE7EBF1)         // --line 分隔线/描边
val LineSoft = Color(0xFFEEF1F6)     // --line-2 浅分隔

// ---- 主色：政务蓝 ----
val Navy = Color(0xFF16263D)         // --navy 深色头图/侧栏强调
val Primary = Color(0xFF1F3A5F)      // --primary
val PrimaryDeep = Color(0xFF2A4F7D)  // 渐变深端（按钮/头图）
val PrimarySoft = Color(0xFFEAF0F7)  // --primary-soft 选中底/标签底

// ---- 强调色：司法红 ----
val Accent = Color(0xFFB4231A)       // --accent 徽标/红头/关键操作
val AccentLight = Color(0xFFD8543F)  // 徽标渐变亮端
val AccentSoft = Color(0xFFFBECEB)   // --accent-soft

// ---- 语义色 ----
val Ok = Color(0xFF2F7D5B)           // 正常/就绪
val OkSoft = Color(0xFFE8F2EC)
val Warn = Color(0xFFC98A14)         // 繁忙/提醒
val WarnSoft = Color(0xFFFBF3E0)
val Blue = Color(0xFF2F6FD0)         // 信息/链接
val BlueSoft = Color(0xFFE9F1FB)
val Purple = Color(0xFF5A3A8A)       // 知识库/AI
val PurpleSoft = Color(0xFFF1EBF8)

// ---- 文本 ----
val Ink = Color(0xFF1A2433)          // --ink 主文本
val Ink2 = Color(0xFF4A5567)         // --ink-2 次级文本
val Muted = Color(0xFF8B95A6)        // --muted 占位/辅助

// ---- 侧栏（浅色政务栏）----
val RailBg = Color(0xFFF4F7FB)       // 侧栏底
val RailBorder = Color(0xFFE3E9F2)
val RailText = Color(0xFF4A5567)     // 未选中菜单文字
val RailActiveBg = Color(0xFFFFFFFF)
val RailActiveFg = Primary
val RailHoverBg = Color(0xFFE9EEF6)

// ---- 顶栏 ----
val TopbarBg = Color(0xFFFFFFFF)
val TopbarBorder = Line

// ============================================================
// 以下为兼容旧引用的别名（历史代码不动也能跟着换肤）
// ============================================================
val MainBg = AppBg
val Background = AppBg

val TextPrimary = Ink
val TextRegular = Ink2
val TextSecondary = Muted
val TextPlaceholder = Muted
val BodyText = Ink
val SecondaryText = Ink2

val DividerColor = Line
val BorderLight = Line
val HoverBlue = PrimarySoft

val EpPrimary = Primary
val EpPrimaryDark = PrimaryDeep
val EpSuccess = Ok
val EpWarning = Warn
val EpDanger = Accent
val EpInfo = Muted

val SidebarBg = RailBg
val SidebarText = RailText
val SidebarActive = Primary           // 头像/选中块底色（配白字）
val SidebarActiveFg = RailActiveFg
val SidebarHover = Color(0x1A1F3A5F)
val SidebarBorder = RailBorder
val SidebarSubText = Muted

// 登录页深色头图
val LoginGradStart = Navy
val LoginGradEnd = PrimaryDeep

// 首页 Banner 渐变
val BannerGradStart = Primary
val BannerGradEnd = PrimaryDeep

// ============================================================
// 功能色系（v3.1）：四大生产力入口与对应工作区的完整彩色视觉
// 每组 4 档：卡片渐变两端 + 浅底（标签/弱化区）+ 深字（浅底上的文字）
// 饱和度收敛，保证政务办公产品的稳重感
// ============================================================

// 智能写作 · 蓝紫
val FeatureWriteStart = Color(0xFF4257C4)
val FeatureWriteEnd = Color(0xFF5D74DE)
val FeatureWriteSoft = Color(0xFFEDF1FD)
val FeatureWriteInk = Color(0xFF33459E)

// 模板中心 · 青绿
val FeatureTemplateStart = Color(0xFF0F7A63)
val FeatureTemplateEnd = Color(0xFF1C9C80)
val FeatureTemplateSoft = Color(0xFFE6F4F0)
val FeatureTemplateInk = Color(0xFF0A6250)

// PPT 助手 · 靛紫
val FeaturePptStart = Color(0xFF50429C)
val FeaturePptEnd = Color(0xFF6E5EC6)
val FeaturePptSoft = Color(0xFFEFECFA)
val FeaturePptInk = Color(0xFF413478)

// 格式校验 · 琥珀
val FeatureCheckStart = Color(0xFFA9660F)
val FeatureCheckEnd = Color(0xFFC5861F)
val FeatureCheckSoft = Color(0xFFFBF1E2)
val FeatureCheckInk = Color(0xFF8A5510)

// ---- 导航 / 画布 ----
val NavBg = Color(0xFFF7F9FC)
val NavBorder = Color(0xFFE7EBF1)
val NavText = Color(0xFF4A5567)
val NavActiveBg = Color(0xFFFFFFFF)
val NavActiveFg = Color(0xFF1F3A5F)
val NavHover = Color(0xFFE9EEF6)

val HomeBg = Color(0xFFF6F8FB)
val Scrim = Color(0x330F1B2E)

// 首页快捷入口（前景色 / 底色）
val QuickBlue = Blue;      val QuickBlueBg = BlueSoft
val QuickPurple = Purple;  val QuickPurpleBg = PurpleSoft
val QuickGreen = Ok;       val QuickGreenBg = OkSoft
val QuickOrange = Warn;    val QuickOrangeBg = WarnSoft
val QuickCyan = Blue;      val QuickCyanBg = BlueSoft
val QuickTeal = Ok;        val QuickTealBg = OkSoft

val PrimaryVariant = PrimaryDeep
val Secondary = Muted
val ErrorColor = Accent
val OnPrimaryText = Color.White
