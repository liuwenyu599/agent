package com.judicialai.desktop.design.theme

import androidx.compose.ui.graphics.Color

/**
 * 调色板（v4.0 视觉语言）
 *
 * 品牌锚点：深海军蓝 / 蓝灰。辅助色按「能力域」划分，不再只有小图标着色：
 * - AI / 智能能力：靛蓝 Indigo → 蓝紫 Violet
 * - 知识 / 模板：青绿 Teal → 翡翠 Emerald
 * - PPT / 创作：紫 Violet / 紫檀
 * - 校验 / 提醒：琥珀 Amber → 橙 Orange
 * - 状态：绿 / 橙 / 红 / 蓝，均成对提供 soft 底
 *
 * 约定：
 * 1. 页面禁止自造色值，一律引用本文件；
 * 2. 文件下半部分的「兼容别名」仅供历史代码引用，新代码请使用语义色名；
 * 3. 低饱和渐变、tonal surface、柔和层次优先；禁止满屏渐变与高饱和彩虹色。
 */

// ---- 品牌锚点：深海军蓝 ----
val Navy = Color(0xFF0E1F38)         // 品牌最深端（Header 底 / 抽屉头图）
val NavySoft = Color(0xFF1B3358)
val Primary = Color(0xFF1B3B62)      // 主色
val PrimaryDeep = Color(0xFF2C5C90)  // 渐变亮端
val PrimarySoft = Color(0xFFE6EEF8)

/** 品牌渐变（仅用于品牌条、功能卡、主视觉，不做全屏铺底） */
val BrandStart = Color(0xFF0F2138)
val BrandMid = Color(0xFF1B3B62)
val BrandEnd = Color(0xFF2E5C8A)

// ---- 表面层级（由深到浅，桌面办公的四层 surface）----
val AppBg = Color(0xFFF3F6FA)        // 应用底色
val SurfaceDeep = Color(0xFFEDF1F7)  // 凹陷层：Header / 抽屉底 / 分区底
val SurfaceSunken = Color(0xFFF1F4F9)// 次级底：表格头 / 内嵌面板
val SurfaceTonal = Color(0xFFF7F9FD) // tonal：卡片内弱分区
val Surface = Color(0xFFFFFFFF)      // 标准卡片
val SurfaceSoft = Color(0xFFF7F9FC)  // 兼容旧名
val SurfaceRaised = Color(0xFFFFFFFF)// 浮动层：抽屉、弹窗、预览

// ---- 描边层级 ----
val LineSubtle = Color(0xFFF0F3F8)   // 极浅：列表内分隔
val Line = Color(0xFFE2E8F0)         // 标准描边
val LineStrong = Color(0xFFCBD5E1)   // 强调描边：hover/选中
val LineSoft = Color(0xFFECF0F6)     // 兼容旧名

// ---- AI / 智能能力：靛蓝 → 蓝紫 ----
val AiIndigo = Color(0xFF2F4E9E)
val AiIndigoDeep = Color(0xFF1E3873)
val AiViolet = Color(0xFF5B47C4)
val AiSoft = Color(0xFFECEFFB)
val AiSoftStrong = Color(0xFFDDE4F7)
val AiLine = Color(0xFFC9D2F0)
val AiInk = Color(0xFF25407F)

// ---- 知识 / 模板：青绿 → 翡翠 ----
val Teal = Color(0xFF0E7C6B)
val TealDeep = Color(0xFF0A5A4E)
val Emerald = Color(0xFF12967F)
val EmeraldSoft = Color(0xFFE4F2EF)
val EmeraldLine = Color(0xFFBFDCD5)
val EmeraldInk = Color(0xFF0A5749)

// ---- PPT / 创作：紫 ----
val Violet = Color(0xFF6244A6)
val VioletDeep = Color(0xFF4A3283)
val VioletSoft = Color(0xFFEFEAF8)
val VioletLine = Color(0xFFD6CDEC)
val VioletInk = Color(0xFF3F2B70)

// ---- 校验 / 提醒：琥珀 → 橙 ----
val Amber = Color(0xFFA86416)
val AmberDeep = Color(0xFF8A4F0D)
val Orange = Color(0xFFC2590F)
val AmberSoft = Color(0xFFFDF2E3)
val AmberLine = Color(0xFFF0DCBC)
val AmberInk = Color(0xFF7C4708)

// ---- 状态 ----
val Ok = Color(0xFF1F7A54)
val OkSoft = Color(0xFFE4F2EA)
val OkLine = Color(0xFFBEDCCB)
val Warn = Color(0xFFB2620C)
val WarnSoft = Color(0xFFFDF1E2)
val WarnLine = Color(0xFFF0D9B8)
val Danger = Color(0xFFB42318)
val DangerSoft = Color(0xFFFDECEA)
val DangerLine = Color(0xFFF5C9C4)
val Info = Color(0xFF1D4ED8)
val InfoSoft = Color(0xFFE8EEFC)

// ---- 政务金：细线 / 徽标点缀 ----
val Gold = Color(0xFFC29A4A)
val GoldLight = Color(0xFFDDBE77)
val GoldSoft = Color(0xFFF8F1E2)

// ---- 司法红：关键操作 / 红头 ----
val Accent = Color(0xFFA8231B)
val AccentLight = Color(0xFFD0503C)
val AccentSoft = Color(0xFFFBEBEA)

// ---- 文本层级 ----
val Ink = Color(0xFF101C2E)          // 主文本
val Ink2 = Color(0xFF43536B)         // 次级文本
val Muted = Color(0xFF78859A)        // 辅助 / 占位
val Muted2 = Color(0xFF9BA6B8)       // 更弱：时间戳、序号
val OnDark = Color(0xE6FFFFFF)       // 深底上的主文本
val OnDarkMuted = Color(0xA6FFFFFF)  // 深底上的次级文本

val Blue = Color(0xFF2A69C9)
val BlueSoft = Color(0xFFE8F0FB)
val Purple = Color(0xFF543780)
val PurpleSoft = Color(0xFFF0EAF7)

// ============================================================
// 以下为兼容旧引用的别名（历史代码不动也能跟着换肤）
// ============================================================
val MainBg = AppBg
val Background = AppBg

val TextPrimary = Ink
val TextRegular = Ink2
val TextSecondary = Muted
val TextPlaceholder = Muted2
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

val SidebarBg = SurfaceDeep
val SidebarText = Ink2
val SidebarActive = Primary
val SidebarActiveFg = Surface
val SidebarHover = Color(0x1A1F3A5F)
val SidebarBorder = Line
val SidebarSubText = Muted

val RailBg = SurfaceDeep
val RailBorder = Line
val RailText = Ink2
val RailActiveBg = Surface
val RailActiveFg = Primary
val RailHoverBg = SurfaceSunken

val TopbarBg = Surface
val TopbarBorder = Line

val LoginGradStart = Navy
val LoginGradEnd = PrimaryDeep
val BannerGradStart = Primary
val BannerGradEnd = PrimaryDeep

val HeroStart = Color(0xFF10223A)
val HeroMid = Color(0xFF1B3B62)
val HeroEnd = Color(0xFF2C5C90)

// ============================================================
// 功能色系（四大生产力入口与对应工作区的完整彩色视觉）
// 每组 6 档：深端 + 渐变亮端 + 浅底 + 深字 + 描边
// ============================================================

// 智能写作 · 政务靛蓝
val FeatureWriteStart = Color(0xFF17386B)
val FeatureWriteEnd = Color(0xFF3C61A8)
val FeatureWriteSoft = Color(0xFFE8EEF9)
val FeatureWriteInk = Color(0xFF153565)
val FeatureWriteLine = Color(0xFF0F2F59)

// 模板中心 · 松柏绿
val FeatureTemplateStart = Color(0xFF0B4E3D)
val FeatureTemplateEnd = Color(0xFF17876A)
val FeatureTemplateSoft = Color(0xFFE3F1EC)
val FeatureTemplateInk = Color(0xFF0A4737)
val FeatureTemplateLine = Color(0xFF083D30)

// PPT 助手 · 紫檀
val FeaturePptStart = Color(0xFF3B2A6B)
val FeaturePptEnd = Color(0xFF6A51A8)
val FeaturePptSoft = Color(0xFFEDE9F7)
val FeaturePptInk = Color(0xFF34245C)
val FeaturePptLine = Color(0xFF2A1D4C)

// 格式校验 · 赭金
val FeatureCheckStart = Color(0xFF7A4C0D)
val FeatureCheckEnd = Color(0xFFB07C22)
val FeatureCheckSoft = Color(0xFFFAF1E1)
val FeatureCheckInk = Color(0xFF6E450C)
val FeatureCheckLine = Color(0xFF5C3908)

// ---- 导航 / 画布 ----
val NavBg = SurfaceDeep
val NavBorder = Line
val NavText = Ink2
val NavActiveBg = Surface
val NavActiveFg = Primary
val NavHover = SurfaceSunken

val HomeBg = AppBg
val Scrim = Color(0x660F1B2E)   // 抽屉遮罩略重，突出上层面板

// 首页快捷入口（前景色 / 底色）
val QuickBlue = Blue;      val QuickBlueBg = BlueSoft
val QuickPurple = Purple;  val QuickPurpleBg = PurpleSoft
val QuickGreen = Ok;       val QuickGreenBg = OkSoft
val QuickOrange = Warn;    val QuickOrangeBg = WarnSoft
val QuickCyan = Blue;      val QuickCyanBg = BlueSoft
val QuickTeal = Teal;      val QuickTealBg = EmeraldSoft

val PrimaryVariant = PrimaryDeep
val Secondary = Muted
val ErrorColor = Accent
val OnPrimaryText = Color.White
