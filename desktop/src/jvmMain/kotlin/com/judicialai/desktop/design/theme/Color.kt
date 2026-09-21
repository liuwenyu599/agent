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
val AppBg = Color(0xFFF1F4F9)        // --bg 应用底色
val Surface = Color(0xFFFFFFFF)      // --surface 卡片/面板
val SurfaceSoft = Color(0xFFF7F9FC)  // 次级面板（会话栏、页面底）
val Line = Color(0xFFE1E7F0)         // --line 分隔线/描边
val LineSoft = Color(0xFFECF0F6)     // --line-2 浅分隔

// ---- 主色：政务蓝 ----
val Navy = Color(0xFF11243C)         // --navy 深色头图/侧栏强调
val Primary = Color(0xFF1B3B62)      // --primary
val PrimaryDeep = Color(0xFF2C5C90)  // 渐变深端（按钮/头图）
val PrimarySoft = Color(0xFFE6EEF8)  // --primary-soft 选中底/标签底

// ---- 政务金：点缀色，用于提升政务质感（细线 / 徽标 / 强调）----
val Gold = Color(0xFFC29A4A)
val GoldLight = Color(0xFFDDBE77)
val GoldSoft = Color(0xFFF8F1E2)

// ---- 强调色：司法红 ----
val Accent = Color(0xFFA8231B)       // --accent 徽标/红头/关键操作
val AccentLight = Color(0xFFD0503C)  // 徽标渐变亮端
val AccentSoft = Color(0xFFFBEBEA)   // --accent-soft

// ---- 语义色 ----
val Ok = Color(0xFF2A7355)           // 正常/就绪
val OkSoft = Color(0xFFE6F1EB)
val Warn = Color(0xFFC0821A)         // 繁忙/提醒
val WarnSoft = Color(0xFFFCF3E2)
val Blue = Color(0xFF2A69C9)         // 信息/链接
val BlueSoft = Color(0xFFE8F0FB)
val Purple = Color(0xFF543780)       // 知识库/AI
val PurpleSoft = Color(0xFFF0EAF7)

// ---- 文本 ----
val Ink = Color(0xFF16202F)          // --ink 主文本
val Ink2 = Color(0xFF46536A)         // --ink-2 次级文本
val Muted = Color(0xFF8693A8)        // --muted 占位/辅助

// ---- 侧栏（浅色政务栏）----
val RailBg = Color(0xFFF4F7FB)       // 侧栏底
val RailBorder = Color(0xFFE3E9F2)
val RailText = Color(0xFF46536A)     // 未选中菜单文字
val RailActiveBg = Color(0xFFFFFFFF)
val RailActiveFg = Primary
val RailHoverBg = Color(0xFFE9EEF6)

// ---- 顶栏 ----
val TopbarBg = Color(0xFFFFFFFF)
val TopbarBorder = Line

// ---- 首页主视觉（政务蓝深渐变 + 金线点缀）----
val HeroStart = Color(0xFF10223A)
val HeroMid = Color(0xFF1B3B62)
val HeroEnd = Color(0xFF2C5C90)

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
// 功能色系（v3.2）：四大生产力入口与对应工作区的完整彩色视觉
// 每组 6 档：深端 + 渐变亮端 + 浅底 + 深字 + 描边，
// 低明度深色主色 + 金色细节，兼顾政务庄重与现代质感
// ============================================================

// 智能写作 · 政务靛蓝
val FeatureWriteStart = Color(0xFF173E70)
val FeatureWriteEnd = Color(0xFF2F6BA4)
val FeatureWriteSoft = Color(0xFFE7EFF9)
val FeatureWriteInk = Color(0xFF143563)
val FeatureWriteLine = Color(0xFF0F2F59)

// 模板中心 · 松柏绿
val FeatureTemplateStart = Color(0xFF0C5341)
val FeatureTemplateEnd = Color(0xFF17795B)
val FeatureTemplateSoft = Color(0xFFE4F1EC)
val FeatureTemplateInk = Color(0xFF0A4737)
val FeatureTemplateLine = Color(0xFF083D30)

// PPT 助手 · 紫檀
val FeaturePptStart = Color(0xFF3E2C6E)
val FeaturePptEnd = Color(0xFF5E4796)
val FeaturePptSoft = Color(0xFFECE8F6)
val FeaturePptInk = Color(0xFF34245C)
val FeaturePptLine = Color(0xFF2A1D4C)

// 格式校验 · 赭金
val FeatureCheckStart = Color(0xFF7E4F0E)
val FeatureCheckEnd = Color(0xFFAE7720)
val FeatureCheckSoft = Color(0xFFFAF1E1)
val FeatureCheckInk = Color(0xFF6E450C)
val FeatureCheckLine = Color(0xFF5C3908)

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
