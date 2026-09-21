package com.judicialai.desktop.design.theme

import androidx.compose.ui.unit.dp

/**
 * 尺寸 token：间距 / 圆角 / 阴影 / 图标 / 布局宽度。
 * 页面内禁止自造数值，一律引用本文件，保证不同页面节奏一致。
 */
object Dimens {

    // ---- 间距 ----
    val space1 = 4.dp
    val space2 = 8.dp
    val space3 = 12.dp
    val space4 = 16.dp
    val space5 = 20.dp
    val space6 = 24.dp
    val space8 = 32.dp
    val space10 = 40.dp

    // ---- 圆角 ----
    val radiusSm = 8.dp
    val radiusMd = 12.dp
    val radiusLg = 16.dp
    val radiusXl = 24.dp
    val radiusPill = 999.dp

    // ---- 阴影（克制，桌面办公产品不使用大面积投影）----
    val elevCard = 1.dp
    val elevRaised = 4.dp
    val elevFloat = 10.dp

    // ---- 图标 ----
    val iconSm = 16.dp
    val iconMd = 20.dp
    val iconLg = 24.dp
    val iconFeature = 44.dp   // 功能卡主图标
    val iconDeco = 112.dp     // 功能卡低透明度装饰图标

    // ---- 布局 ----
    val headerHeight = 60.dp
    val navWidth = 236.dp
    val navWidthCollapsed = 68.dp
    val drawerWidth = 440.dp
    val homeMaxWidth = 1180.dp
}
