package com.judicialai.desktop.design.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsHoveredAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.Icon
import androidx.compose.material.Surface
import androidx.compose.material.Text
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AccountBalance
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Home
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.app.AppNav
import com.judicialai.desktop.app.AppScreen
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.app.NavGroup
import com.judicialai.desktop.app.NavItem
import com.judicialai.desktop.design.theme.AiIndigo
import com.judicialai.desktop.design.theme.BrandEnd
import com.judicialai.desktop.design.theme.BrandStart
import com.judicialai.desktop.design.theme.Dimens
import com.judicialai.desktop.design.theme.FeatureCheckEnd
import com.judicialai.desktop.design.theme.FeatureCheckStart
import com.judicialai.desktop.design.theme.FeaturePptEnd
import com.judicialai.desktop.design.theme.FeaturePptStart
import com.judicialai.desktop.design.theme.FeatureTemplateEnd
import com.judicialai.desktop.design.theme.FeatureTemplateStart
import com.judicialai.desktop.design.theme.FeatureWriteEnd
import com.judicialai.desktop.design.theme.FeatureWriteStart
import com.judicialai.desktop.design.theme.HeaderNavy
import com.judicialai.desktop.design.theme.Ink
import com.judicialai.desktop.design.theme.Ink2
import com.judicialai.desktop.design.theme.Line
import com.judicialai.desktop.design.theme.LineStrong
import com.judicialai.desktop.design.theme.Muted
import com.judicialai.desktop.design.theme.OnDark
import com.judicialai.desktop.design.theme.OnDarkMuted
import com.judicialai.desktop.design.theme.OnPrimaryText
import com.judicialai.desktop.design.theme.Primary
import com.judicialai.desktop.design.theme.Scrim
import com.judicialai.desktop.design.theme.Surface as SurfaceColor
import com.judicialai.desktop.design.theme.SurfaceDeep
import com.judicialai.desktop.design.theme.SurfaceTonal

/** 四大入口的功能色（抽屉、工作区标题、卡片共用同一来源） */
data class FeaturePalette(val start: Color, val end: Color)

fun paletteOf(screen: AppScreen): FeaturePalette = when (screen) {
    AppScreen.WRITING -> FeaturePalette(FeatureWriteStart, FeatureWriteEnd)
    AppScreen.TEMPLATES -> FeaturePalette(FeatureTemplateStart, FeatureTemplateEnd)
    AppScreen.PPT -> FeaturePalette(FeaturePptStart, FeaturePptEnd)
    AppScreen.FORMAT_CHECK -> FeaturePalette(FeatureCheckStart, FeatureCheckEnd)
    else -> FeaturePalette(BrandStart, BrandEnd)
}

/**
 * 全局导航抽屉（v4.0）
 * 与 Header 共用品牌渐变头条，内容区为简洁菜单列表（不再放 HOME 的彩色功能卡）。
 */
@Composable
fun GlobalNavDrawer(
    isAdmin: Boolean,
    onNavigate: (NavItem) -> Unit,
    onHome: () -> Unit,
    onDismiss: () -> Unit,
) {
    Box(
        Modifier.fillMaxSize().background(Scrim).clickable(
            interactionSource = remember { MutableInteractionSource() },
            indication = null, onClick = onDismiss,
        )
    ) {
        Surface(
            modifier = Modifier.align(Alignment.CenterStart)
                .width(Dimens.drawerWidth).fillMaxHeight(),
            shape = RoundedCornerShape(0.dp),
            color = SurfaceColor,
            elevation = Dimens.elevFloat,
        ) {
            Column(Modifier.fillMaxSize()) {
                DrawerHeader(onDismiss)

                Column(
                    Modifier.weight(1f).verticalScroll(rememberScrollState())
                        .padding(horizontal = Dimens.space5, vertical = Dimens.space4),
                ) {
                    val query = AppState.navQuery.trim()
                    val match: (NavItem) -> Boolean = {
                        query.isBlank() || it.label.contains(query, true)
                    }

                    DrawerHomeRow(onHome = onHome)
                    Spacer(Modifier.height(Dimens.space5))

                    for (group in AppNav.drawerGroups()) {
                        // AppNav.drawerGroups() 已按当前角色构造管理分组：
                        // 普通用户无管理组，科室管理员仅本科室配置，系统管理员才有账号管理。
                        val items = group.items.filter(match)
                        if (items.isEmpty()) continue
                        DrawerGroupTitle(group)
                        Spacer(Modifier.height(Dimens.space2))
                        Column(
                            Modifier.fillMaxWidth()
                                .clip(RoundedCornerShape(Dimens.radiusLg))
                                .background(SurfaceTonal)
                                .border(1.dp, Line, RoundedCornerShape(Dimens.radiusLg))
                                .padding(Dimens.space2),
                            verticalArrangement = Arrangement.spacedBy(2.dp),
                        ) {
                            items.forEach { item -> DrawerRow(item = item, onNavigate = onNavigate) }
                        }
                        Spacer(Modifier.height(Dimens.space4))
                    }
                    Spacer(Modifier.height(Dimens.space4))
                }
            }
        }
    }
}

@Composable
private fun DrawerHeader(onDismiss: () -> Unit) {
    val decor = OnPrimaryText
    Box(
        Modifier.fillMaxWidth()
            // 与顶栏同一藏青，保证「侧边栏头条 = 顶栏」颜色一致
            .background(HeaderNavy)
            // 低饱和几何装饰用 drawBehind 绘制：不参与测量，避免撑高抽屉头部
            .drawBehind {
                drawCircle(
                    color = decor, alpha = 0.06f, radius = 88.dp.toPx(),
                    center = Offset(size.width - 22.dp.toPx(), -26.dp.toPx()),
                )
            }
            .padding(horizontal = Dimens.space6, vertical = Dimens.space5),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                Modifier.size(42.dp).clip(RoundedCornerShape(Dimens.radiusMd))
                    .background(OnPrimaryText.copy(alpha = 0.16f)),
                contentAlignment = Alignment.Center,
            ) {
                Icon(Icons.Default.AccountBalance, contentDescription = null,
                    tint = OnPrimaryText, modifier = Modifier.size(Dimens.iconLg))
            }
            Spacer(Modifier.width(Dimens.space3))
            Column(Modifier.weight(1f)) {
                Text("白云司法局智慧办公平台", fontSize = 15.sp,
                    fontWeight = FontWeight.SemiBold, color = OnDark)
                Spacer(Modifier.height(2.dp))
                Text(
                    buildString {
                        append("全局导航")
                        if (AppState.departmentName.isNotBlank()) {
                            append(" · ")
                            append(AppState.departmentName)
                        }
                    },
                    fontSize = 11.5.sp, color = OnDarkMuted,
                )
            }
            Box(
                Modifier.size(32.dp).clip(RoundedCornerShape(Dimens.radiusSm))
                    .background(OnPrimaryText.copy(alpha = 0.12f))
                    .clickable(onClick = onDismiss),
                contentAlignment = Alignment.Center,
            ) {
                Icon(Icons.Default.Close, contentDescription = "关闭导航",
                    tint = OnDark, modifier = Modifier.size(Dimens.iconMd))
            }
        }
    }
}

@Composable
private fun DrawerGroupTitle(group: NavGroup) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.width(3.dp).height(14.dp).clip(CircleShape).background(AiIndigo))
        Spacer(Modifier.width(Dimens.space2))
        Text(group.title, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = Ink)
    }
}

@Composable
private fun DrawerHomeRow(onHome: () -> Unit) {
    val interaction = remember { MutableInteractionSource() }
    val hovered by interaction.collectIsHoveredAsState()
    Row(
        Modifier.fillMaxWidth()
            .clip(RoundedCornerShape(Dimens.radiusLg))
            .background(if (hovered) SurfaceDeep else SurfaceColor)
            .border(1.dp, if (hovered) LineStrong else Line,
                RoundedCornerShape(Dimens.radiusLg))
            .clickable(interactionSource = interaction, indication = null, onClick = onHome)
            .padding(horizontal = Dimens.space4, vertical = Dimens.space3 + 2.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier.size(34.dp).clip(RoundedCornerShape(Dimens.radiusMd))
                .background(Brush.linearGradient(listOf(BrandStart, BrandEnd))),
            contentAlignment = Alignment.Center,
        ) {
            Icon(Icons.Default.Home, contentDescription = null, tint = OnPrimaryText,
                modifier = Modifier.size(Dimens.iconMd))
        }
        Spacer(Modifier.width(Dimens.space3))
        Text("工作台", fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = Ink,
            modifier = Modifier.weight(1f))
        Text("进入 →", fontSize = 11.5.sp, color = Primary)
    }
}

@Composable
private fun DrawerRow(item: NavItem, onNavigate: (NavItem) -> Unit) {
    val interaction = remember { MutableInteractionSource() }
    val hovered by interaction.collectIsHoveredAsState()
    val active = AppState.screen == item.screen
    val shape = RoundedCornerShape(Dimens.radiusMd)
    Row(
        Modifier.fillMaxWidth()
            .clip(shape)
            .background(
                when {
                    active -> SurfaceColor
                    hovered -> SurfaceDeep
                    else -> Color.Transparent
                }
            )
            .border(
                1.dp,
                if (active) Primary.copy(alpha = 0.35f) else if (hovered) Line else Color.Transparent,
                shape,
            )
            .clickable(interactionSource = interaction, indication = null) { onNavigate(item) }
            .padding(horizontal = Dimens.space3, vertical = Dimens.space2 + 2.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier.size(30.dp).clip(RoundedCornerShape(Dimens.radiusSm))
                .background(
                    if (active) Brush.linearGradient(listOf(BrandStart, BrandEnd))
                    else Brush.linearGradient(listOf(SurfaceDeep, SurfaceDeep))
                ),
            contentAlignment = Alignment.Center,
        ) {
            Icon(item.icon, contentDescription = null,
                tint = if (active) OnPrimaryText else Ink2,
                modifier = Modifier.size(Dimens.iconSm))
        }
        Spacer(Modifier.width(Dimens.space3))
        Text(item.label, fontSize = 13.sp,
            fontWeight = if (active) FontWeight.SemiBold else FontWeight.Normal,
            color = if (active) Primary else Ink)
    }
}
