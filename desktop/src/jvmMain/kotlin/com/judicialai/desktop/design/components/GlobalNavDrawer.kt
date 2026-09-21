package com.judicialai.desktop.design.components

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.Icon
import androidx.compose.material.OutlinedTextField
import androidx.compose.material.Text
import androidx.compose.material.TextFieldDefaults
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Search
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.app.AppNav
import com.judicialai.desktop.app.AppScreen
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.app.NavGroup
import com.judicialai.desktop.app.NavItem
import com.judicialai.desktop.design.theme.Dimens
import com.judicialai.desktop.design.theme.FeatureCheckEnd
import com.judicialai.desktop.design.theme.FeatureCheckStart
import com.judicialai.desktop.design.theme.FeaturePptEnd
import com.judicialai.desktop.design.theme.FeaturePptStart
import com.judicialai.desktop.design.theme.FeatureTemplateEnd
import com.judicialai.desktop.design.theme.FeatureTemplateStart
import com.judicialai.desktop.design.theme.FeatureWriteEnd
import com.judicialai.desktop.design.theme.FeatureWriteStart
import com.judicialai.desktop.design.theme.Ink
import com.judicialai.desktop.design.theme.Ink2
import com.judicialai.desktop.design.theme.Line
import com.judicialai.desktop.design.theme.Muted
import com.judicialai.desktop.design.theme.Primary
import com.judicialai.desktop.design.theme.Scrim
import com.judicialai.desktop.design.theme.Surface

/** 四大入口的功能色（抽屉、工作区标题、卡片共用同一来源） */
data class FeaturePalette(val start: Color, val end: Color)

fun paletteOf(screen: AppScreen): FeaturePalette = when (screen) {
    AppScreen.WRITING -> FeaturePalette(FeatureWriteStart, FeatureWriteEnd)
    AppScreen.TEMPLATES -> FeaturePalette(FeatureTemplateStart, FeatureTemplateEnd)
    AppScreen.PPT -> FeaturePalette(FeaturePptStart, FeaturePptEnd)
    AppScreen.FORMAT_CHECK -> FeaturePalette(FeatureCheckStart, FeatureCheckEnd)
    else -> FeaturePalette(Primary, Primary)
}

/**
 * 全局导航抽屉：点击顶部品牌名展开。
 * 搜索仅过滤本导航项（真实过滤，不做假数据检索）；三组按层级分区，不平铺成一列菜单。
 */
@Composable
fun GlobalNavDrawer(
    isAdmin: Boolean,
    onNavigate: (NavItem) -> Unit,
    onHome: () -> Unit,
    onDismiss: () -> Unit,
) {
    Box(Modifier.fillMaxSize().background(Scrim).clickable(
        interactionSource = remember { androidx.compose.foundation.interaction.MutableInteractionSource() },
        indication = null, onClick = onDismiss,
    )) {
        Column(
            Modifier.align(Alignment.CenterStart).width(Dimens.drawerWidth).fillMaxHeight()
                .background(Surface)
                .clickable(
                    interactionSource = remember { androidx.compose.foundation.interaction.MutableInteractionSource() },
                    indication = null, onClick = {},
                )
                .padding(Dimens.space5),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("白云司法局智慧办公平台", fontSize = 15.sp,
                        fontWeight = FontWeight.SemiBold, color = Ink)
                    Text("全局导航", fontSize = 12.sp, color = Muted)
                }
                Box(
                    Modifier.size(30.dp).clip(RoundedCornerShape(Dimens.radiusSm))
                        .clickable(onClick = onDismiss), contentAlignment = Alignment.Center,
                ) {
                    Icon(Icons.Default.Close, contentDescription = "关闭导航",
                        tint = Muted, modifier = Modifier.size(Dimens.iconMd))
                }
            }

            Spacer(Modifier.height(Dimens.space4))
            OutlinedTextField(
                value = AppState.navQuery,
                onValueChange = { AppState.navQuery = it },
                placeholder = { Text("搜索功能，例如：模板、审批、PPT", fontSize = 12.5.sp,
                    color = Muted) },
                leadingIcon = { Icon(Icons.Default.Search, null, tint = Muted,
                    modifier = Modifier.size(Dimens.iconMd)) },
                singleLine = true,
                modifier = Modifier.fillMaxWidth().height(46.dp),
                colors = TextFieldDefaults.outlinedTextFieldColors(
                    focusedBorderColor = Primary, cursorColor = Primary,
                    unfocusedBorderColor = Line),
            )

            Spacer(Modifier.height(Dimens.space4))
            Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
                val query = AppState.navQuery.trim()
                val match: (NavItem) -> Boolean = {
                    query.isBlank() || it.label.contains(query, true) || it.desc.contains(query, true)
                }

                DrawerHomeRow(onHome = onHome)

                for (group in AppNav.drawerGroups) {
                    val items = group.items.filter { it.screen != AppScreen.ADMIN || isAdmin }
                        .filter(match)
                    if (items.isEmpty()) continue
                    Spacer(Modifier.height(Dimens.space5))
                    DrawerGroupTitle(group)
                    Spacer(Modifier.height(Dimens.space3))
                    if (group.key == "core") {
                        DrawerCoreGrid(items, onNavigate)
                    } else {
                        items.forEach { item ->
                            DrawerRow(item = item, onNavigate = onNavigate)
                            Spacer(Modifier.height(Dimens.space1))
                        }
                    }
                }
                Spacer(Modifier.height(Dimens.space5))
            }
        }
    }
}

@Composable
private fun DrawerGroupTitle(group: NavGroup) {
    Column {
        Text(group.title, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = Ink)
        Text(group.desc, fontSize = 11.5.sp, color = Muted)
    }
}

@Composable
private fun DrawerHomeRow(onHome: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(Dimens.radiusMd))
            .background(com.judicialai.desktop.design.theme.HomeBg)
            .clickable(onClick = onHome)
            .padding(horizontal = Dimens.space4, vertical = Dimens.space3),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(Icons.Default.Home, contentDescription = null, tint = Primary,
            modifier = Modifier.size(Dimens.iconMd))
        Spacer(Modifier.width(Dimens.space3))
        Column(Modifier.weight(1f)) {
            Text("工作台", fontSize = 13.5.sp, fontWeight = FontWeight.SemiBold, color = Ink)
            Text("今天可以做什么", fontSize = 11.5.sp, color = Muted)
        }
    }
}

@Composable
private fun DrawerCoreGrid(items: List<NavItem>, onNavigate: (NavItem) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(Dimens.space3)) {
        items.chunked(2).forEach { row ->
            Row(horizontalArrangement = Arrangement.spacedBy(Dimens.space3)) {
                row.forEach { item ->
                    val p = paletteOf(item.screen)
                    Box(
                        Modifier.weight(1f).height(84.dp)
                            .clip(RoundedCornerShape(Dimens.radiusMd))
                            .background(Brush.linearGradient(listOf(p.start, p.end)))
                            .clickable { onNavigate(item) }
                            .padding(Dimens.space4),
                    ) {
                        Column {
                            Icon(item.icon, contentDescription = null, tint = Color.White,
                                modifier = Modifier.size(Dimens.iconLg))
                            Spacer(Modifier.height(Dimens.space2))
                            Text(item.label, fontSize = 13.5.sp, fontWeight = FontWeight.SemiBold,
                                color = Color.White, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            Text(item.desc, fontSize = 11.sp,
                                color = Color.White.copy(alpha = 0.85f),
                                maxLines = 1, overflow = TextOverflow.Ellipsis)
                        }
                    }
                }
                if (row.size == 1) Spacer(Modifier.weight(1f))
            }
        }
    }
}

@Composable
private fun DrawerRow(item: NavItem, onNavigate: (NavItem) -> Unit) {
    Row(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(Dimens.radiusSm))
            .clickable { onNavigate(item) }
            .padding(horizontal = Dimens.space3, vertical = Dimens.space2 + 2.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(item.icon, contentDescription = null, tint = Ink2,
            modifier = Modifier.size(Dimens.iconMd))
        Spacer(Modifier.width(Dimens.space3))
        Column(Modifier.weight(1f)) {
            Text(item.label, fontSize = 13.sp, color = Ink)
            if (item.desc.isNotBlank()) {
                Text(item.desc, fontSize = 11.5.sp, color = Muted,
                    maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}
