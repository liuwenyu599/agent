package com.judicialai.desktop.design.theme

import androidx.compose.ui.unit.dp

/**
 * 尺寸 token（v4.0）：间距 / 圆角 / 控件高度 / 阴影 / 图标 / 布局宽度。
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
    val space7 = 28.dp
    val space8 = 32.dp
    val space10 = 40.dp

    // ---- 圆角层级（控件 < 卡片 < 面板 < 大块）----
    val radiusXs = 6.dp
    val radiusSm = 8.dp      // 标签、小按钮
    val radiusControl = 10.dp// 输入框 / 下拉
    val radiusMd = 12.dp     // 卡片
    val radiusLg = 16.dp     // 面板 / 抽屉内容块
    val radiusXl = 20.dp     // 大卡 / 功能卡
    val radiusSheet = 24.dp  // 抽屉 / 文档纸张
    val radiusPill = 999.dp

    // ---- 控件高度 ----
    val hSm = 32.dp
    val hControl = 40.dp     // 输入框 / 下拉标准高
    val hControlLg = 52.dp   // 带 label 的下拉
    val hButton = 38.dp
    val hButtonLg = 44.dp

    // ---- 阴影层级 ----
    val elevNone = 0.dp
    val elevCard = 1.dp
    val elevRaised = 3.dp
    val elevFloat = 8.dp
    val elevDialog = 16.dp

    // ---- 图标 ----
    val iconXs = 14.dp
    val iconSm = 16.dp
    val iconMd = 20.dp
    val iconLg = 24.dp
    val iconXl = 28.dp
    val iconFeature = 46.dp
    val iconDeco = 112.dp

    // ---- 布局 ----
    val headerHeight = 64.dp
    val navWidth = 236.dp
    val navWidthCollapsed = 68.dp
    val drawerWidth = 420.dp
    val homeMaxWidth = 1160.dp
    val contentMaxWidth = 1560.dp
}
