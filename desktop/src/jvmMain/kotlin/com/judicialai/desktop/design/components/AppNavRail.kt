package com.judicialai.desktop.design.components

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.hoverable
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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.Icon
import androidx.compose.material.Text
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.KeyboardArrowLeft
import androidx.compose.material.icons.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.PushPin
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.app.AppNav
import com.judicialai.desktop.app.AppScreen
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.app.NavItem
import com.judicialai.desktop.design.theme.Dimens
import com.judicialai.desktop.design.theme.Ink
import com.judicialai.desktop.design.theme.Muted
import com.judicialai.desktop.design.theme.NavActiveBg
import com.judicialai.desktop.design.theme.NavActiveFg
import com.judicialai.desktop.design.theme.NavBg
import com.judicialai.desktop.design.theme.NavBorder
import com.judicialai.desktop.design.theme.NavHover
import com.judicialai.desktop.design.theme.NavText

/**
 * 工作区导航：只在非 HOME 页面出现，属导航工具而非视觉主体。
 * 支持展开 / 收起（图标条）/ 固定（pin），选中态为白底 + 主色文字 + 左侧色条。
 */
@Composable
fun AppNavRail(
    current: AppScreen,
    isAdmin: Boolean,
    modifier: Modifier = Modifier,
    onNavigate: (NavItem) -> Unit,
) {
    val collapsed = AppState.navCollapsed
    val pinned = AppState.navPinned
    val width = if (collapsed) Dimens.navWidthCollapsed else AppState.navWidth.dp

    Box(modifier.width(width).fillMaxHeight()) {
    Column(
        Modifier.fillMaxSize().background(NavBg)
            .padding(vertical = Dimens.space3),
    ) {
        // 折叠 / 固定控制条
        Row(
            Modifier.fillMaxWidth().padding(horizontal = Dimens.space3, vertical = Dimens.space1),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (!collapsed) {
                Text("工作区", fontSize = 12.sp, color = Muted,
                    fontWeight = FontWeight.Medium, modifier = Modifier.weight(1f))
            } else {
                Spacer(Modifier.weight(1f))
            }
            Box(
                Modifier.size(26.dp).clip(RoundedCornerShape(Dimens.radiusSm))
                    .clickable { AppState.navPinned = !pinned }
                    .padding(Dimens.space1),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    Icons.Default.PushPin, contentDescription = if (pinned) "取消固定" else "固定导航",
                    tint = if (pinned) NavActiveFg else Muted, modifier = Modifier.size(Dimens.iconSm),
                )
            }
            Spacer(Modifier.width(Dimens.space1))
            Box(
                Modifier.size(26.dp).clip(RoundedCornerShape(Dimens.radiusSm))
                    .clickable { AppState.navCollapsed = !collapsed }
                    .padding(Dimens.space1),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    if (collapsed) Icons.Default.KeyboardArrowRight else Icons.Default.KeyboardArrowLeft,
                    contentDescription = if (collapsed) "展开导航" else "收起导航",
                    tint = Muted, modifier = Modifier.size(Dimens.iconSm),
                )
            }
        }

        Spacer(Modifier.height(Dimens.space2))
        Box(Modifier.fillMaxWidth().height(1.dp).background(NavBorder))

        Column(
            Modifier.weight(1f).verticalScroll(rememberScrollState())
                .padding(vertical = Dimens.space2, horizontal = Dimens.space2),
            verticalArrangement = Arrangement.spacedBy(Dimens.space1),
        ) {
            for (group in AppNav.groups) {
                val visible = group.items.filter { it.screen != AppScreen.ADMIN || isAdmin }
                if (visible.isEmpty()) continue
                if (!collapsed) {
                    Text(
                        group.title, fontSize = 11.5.sp, color = Muted,
                        fontWeight = FontWeight.Medium,
                        modifier = Modifier.padding(start = Dimens.space3, top = Dimens.space3,
                            bottom = Dimens.space1),
                    )
                } else {
                    Spacer(Modifier.height(Dimens.space2))
                }
                for (item in visible) {
                    NavRailItem(
                        item = item,
                        selected = item.screen == current && current != AppScreen.HOME,
                        collapsed = collapsed,
                        onClick = { onNavigate(item) },
                    )
                }
            }
        }
    }

    // 右侧拖拽把手：拖动调节导航宽度（180–420dp），收起状态下不可拖
    if (!collapsed) {
        val handleInteraction = remember { MutableInteractionSource() }
        val handleHovered by handleInteraction.collectIsHoveredAsState()
        Box(
            Modifier.align(Alignment.CenterEnd).width(10.dp).fillMaxHeight()
                .hoverable(handleInteraction)
                .pointerInput(Unit) {
                    detectDragGestures { _, dragAmount ->
                        AppState.navWidth = (AppState.navWidth + dragAmount.x).coerceIn(180f, 420f)
                    }
                },
        ) {
            Box(
                Modifier.align(Alignment.Center).fillMaxHeight()
                    .width(if (handleHovered) 3.dp else 1.dp)
                    .background(if (handleHovered) NavActiveFg else NavBorder),
            )
        }
    }
    }
}

@Composable
private fun NavRailItem(
    item: NavItem,
    selected: Boolean,
    collapsed: Boolean,
    onClick: () -> Unit,
) {
    val interaction = remember { MutableInteractionSource() }
    val hovered by interaction.collectIsHoveredAsState()
    val bg = when {
        selected -> NavActiveBg
        hovered -> NavHover
        else -> Color.Transparent
    }
    val fg = if (selected) NavActiveFg else NavText

    Row(
        Modifier.fillMaxWidth().height(38.dp)
            .clip(RoundedCornerShape(Dimens.radiusSm))
            .background(bg)
            .clickable(interactionSource = interaction, indication = null, onClick = onClick)
            .then(if (collapsed) Modifier else Modifier.padding(start = Dimens.space2)),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (selected && !collapsed) {
            Box(
                Modifier.width(3.dp).height(18.dp)
                    .clip(RoundedCornerShape(Dimens.radiusPill)).background(NavActiveFg),
            )
            Spacer(Modifier.width(Dimens.space2 - 3.dp))
        }
        if (collapsed) {
            Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                Icon(item.icon, contentDescription = item.label, tint = fg,
                    modifier = Modifier.size(Dimens.iconMd))
            }
        } else {
            if (!selected) Spacer(Modifier.width(Dimens.space2))
            Icon(item.icon, contentDescription = item.label, tint = fg,
                modifier = Modifier.size(Dimens.iconMd))
            Spacer(Modifier.width(Dimens.space3))
            Text(
                item.label, fontSize = 13.sp, color = if (selected) Ink else NavText,
                fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
                maxLines = 1, overflow = TextOverflow.Ellipsis,
            )
        }
    }
}
