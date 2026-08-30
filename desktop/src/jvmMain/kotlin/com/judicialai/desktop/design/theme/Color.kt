package com.judicialai.desktop.design.theme

import androidx.compose.ui.graphics.Color

/**
 * 调色板：1:1 取自 Web 端（AppLayout.vue / DashboardView.vue / Element Plus）。
 * 不允许自造色值，新增颜色必须能对应到 Web 端某个 CSS 值。
 */
// ---- 布局骨架 ----
val SidebarBg = Color(0xFF16223F)          // .sidebar background
val SidebarText = Color(0xFFB0C4DE)        // el-menu text-color
val SidebarActive = Color(0xFF2F5CFF)      // .el-menu-item.is-active background
val SidebarHover = Color(0x14FFFFFF)       // rgba(255,255,255,0.08)
val SidebarBorder = Color(0x14FFFFFF)      // rgba(255,255,255,0.08)
val SidebarSubText = Color(0x80FFFFFF)     // rgba(255,255,255,0.5)
val MainBg = Color(0xFFF0F2F5)             // .main-content background
val TopbarBorder = Color(0xFFEBEEF5)       // .topbar border-bottom

// ---- Element Plus 主色 ----
val EpPrimary = Color(0xFF409EFF)
val EpPrimaryDark = Color(0xFF1A5FB4)      // 登录渐变/用户气泡
val EpSuccess = Color(0xFF67C23A)
val EpWarning = Color(0xFFE6A23C)
val EpDanger = Color(0xFFF56C6C)
val EpInfo = Color(0xFF909399)

// ---- 文本 ----
val TextPrimary = Color(0xFF303133)
val TextRegular = Color(0xFF606266)
val TextSecondary = Color(0xFF909399)
val TextPlaceholder = Color(0xFFC0C4CC)

// ---- 表面 ----
val Surface = Color(0xFFFFFFFF)
val SurfaceSoft = Color(0xFFF5F7FA)        // 会话侧栏/知识库页底
val DividerColor = Color(0xFFE4E7ED)
val BorderLight = Color(0xFFEBEEF5)
val HoverBlue = Color(0xFFECF5FF)          // session-item hover

// ---- 登录页渐变 ----
val LoginGradStart = Color(0xFF1A5FB4)
val LoginGradEnd = Color(0xFF4A90D9)

// ---- 首页 Banner 渐变 ----
val BannerGradStart = Color(0xFF1C4F9E)
val BannerGradEnd = Color(0xFF3182CE)

// ---- 首页快速入口（前景色 / 底色）----
val QuickBlue = Color(0xFF2B6CB0);   val QuickBlueBg = Color(0xFFE8F0FE)
val QuickPurple = Color(0xFF7C5CD6); val QuickPurpleBg = Color(0xFFF3EAFD)
val QuickGreen = Color(0xFF38A169);  val QuickGreenBg = Color(0xFFE6F7EE)
val QuickOrange = Color(0xFFDD6B20); val QuickOrangeBg = Color(0xFFFDEEE4)
val QuickCyan = Color(0xFF3182CE);   val QuickCyanBg = Color(0xFFE3F2FD)
val QuickTeal = Color(0xFF2C9A8A);   val QuickTealBg = Color(0xFFE6FFFA)

// ---- 兼容旧引用（逐步替换后删除）----
val Primary = EpPrimary
val PrimaryVariant = EpPrimaryDark
val Secondary = EpInfo
val Background = MainBg
val ErrorColor = EpDanger
val OnPrimaryText = Color.White
val BodyText = TextPrimary
val SecondaryText = TextRegular

