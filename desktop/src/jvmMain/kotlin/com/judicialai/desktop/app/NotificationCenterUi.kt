package com.judicialai.desktop.app

import androidx.compose.animation.core.animateFloatAsState
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
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.DropdownMenu
import androidx.compose.material.Icon
import androidx.compose.material.Surface
import androidx.compose.material.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.design.theme.Dimens
import com.judicialai.desktop.design.theme.Ink
import com.judicialai.desktop.design.theme.Ink2
import com.judicialai.desktop.design.theme.Line
import com.judicialai.desktop.design.theme.Muted
import com.judicialai.desktop.design.theme.Muted2
import com.judicialai.desktop.design.theme.Primary
import com.judicialai.desktop.design.theme.VioletInk
import kotlinx.coroutines.delay
import java.util.concurrent.TimeUnit
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowForward
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.NotificationsActive
import androidx.compose.material.icons.filled.NotificationsNone
import androidx.compose.material.icons.filled.PlayArrow

/**
 * 顶栏通知喇叭（右上角）。
 *
 * 同时承担两件事：
 * - 全局未读角标：任一窗口里任务完成都会让角标 +1；
 * - 点击展开通知列表（与顶栏深色底同款白描边按钮，保证藏青背景上可见）。
 */
@Composable
fun NotificationBell() {
    val unread = NotificationCenter.unreadCount
    var open by remember { mutableStateOf(false) }
    val bellIcon =
        if (unread > 0) Icons.Default.NotificationsActive else Icons.Default.NotificationsNone
    Box {
        val interaction = remember { MutableInteractionSource() }
        val hovered by interaction.collectIsHoveredAsState()
        val bg = if (hovered) Color.White.copy(alpha = 0.16f) else Color.White.copy(alpha = 0.08f)
        val border =
            if (hovered) Color.White.copy(alpha = 0.34f) else Color.White.copy(alpha = 0.18f)
        Box(
            Modifier.size(36.dp)
                .clip(RoundedCornerShape(Dimens.radiusControl))
                .background(bg)
                .border(1.dp, border, RoundedCornerShape(Dimens.radiusControl))
                .clickable(interactionSource = interaction, indication = null) { open = !open },
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                bellIcon,
                contentDescription = "通知中心",
                tint = Color.White.copy(alpha = 0.9f),
                modifier = Modifier.size(Dimens.iconMd),
            )
            if (unread > 0) {
                Box(
                    Modifier.align(Alignment.TopEnd)
                        .size(16.dp)
                        .clip(CircleShape)
                        .background(Color(0xFFE5484D)),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        if (unread > 99) "99+" else "$unread",
                        fontSize = 9.sp,
                        color = Color.White,
                        fontWeight = FontWeight.Bold,
                    )
                }
            }
        }

        DropdownMenu(
            expanded = open,
            onDismissRequest = { open = false },
            modifier = Modifier.widthIn(min = 320.dp, max = 380.dp),
        ) {
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("通知", fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = Ink)
                Spacer(Modifier.weight(1f))
                if (unread > 0) {
                    Box(
                        Modifier.clip(RoundedCornerShape(Dimens.radiusPill))
                            .background(Primary.copy(alpha = 0.1f))
                            .clickable { NotificationCenter.markAllRead() }
                            .padding(horizontal = 10.dp, vertical = 4.dp),
                    ) {
                        Text("全部标为已读", fontSize = 12.sp, color = Primary)
                    }
                }
            }
            Box(Modifier.fillMaxWidth().height(1.dp).background(Line))
            val list = NotificationCenter.items.toList()
            if (list.isEmpty()) {
                Box(Modifier.fillMaxWidth().padding(28.dp), contentAlignment = Alignment.Center) {
                    Text("暂无通知", fontSize = 12.5.sp, color = Muted)
                }
            } else {
                Column(
                    Modifier.fillMaxWidth()
                        .heightIn(max = 380.dp)
                        .verticalScroll(rememberScrollState()),
                ) {
                    list.forEach { n ->
                        NotificationRow(n) {
                            NotificationCenter.markAllRead()
                            navigateFromNotification(n)
                            open = false
                        }
                        Box(Modifier.fillMaxWidth().height(1.dp).background(Line))
                    }
                }
            }
        }
    }
}

@Composable
private fun NotificationRow(n: AppNotification, onClick: () -> Unit) {
    val icon: ImageVector = when (n.kind) {
        "writing" -> Icons.Default.Edit
        "ppt" -> Icons.Default.PlayArrow
        "format" -> Icons.Default.CheckCircle
        else -> Icons.Default.Info
    }
    val iconTint: Color = when (n.kind) {
        "ppt" -> VioletInk
        "format" -> Primary
        "writing" -> Ink2
        else -> Muted
    }
    Row(
        Modifier.fillMaxWidth().clickable { onClick() }
            .padding(horizontal = 16.dp, vertical = 11.dp),
        verticalAlignment = Alignment.Top,
    ) {
        Icon(icon, null, tint = iconTint, modifier = Modifier.size(18.dp).padding(top = 1.dp))
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f)) {
            Text(
                n.title,
                fontSize = 13.sp,
                fontWeight = FontWeight.Medium,
                color = Ink,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Spacer(Modifier.height(3.dp))
            Text(
                n.body,
                fontSize = 11.5.sp,
                color = Muted2,
                lineHeight = 16.sp,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
            Spacer(Modifier.height(4.dp))
            Text(relativeTime(n.createdAt), fontSize = 10.sp, color = Muted)
        }
        if (n.screen != null) {
            Icon(
                Icons.AutoMirrored.Filled.ArrowForward,
                null,
                tint = Primary,
                modifier = Modifier.size(15.dp).padding(top = 2.dp),
            )
        }
    }
}

private fun relativeTime(ts: Long): String {
    val diff = System.currentTimeMillis() - ts
    val min = TimeUnit.MILLISECONDS.toMinutes(diff)
    return when {
        min < 1 -> "刚刚"
        min < 60 -> "$min 分钟前"
        else -> "${TimeUnit.MILLISECONDS.toHours(diff)} 小时前"
    }
}

/**
 * 全局完成弹窗宿主：渲染 [NotificationCenter.popup]，6 秒后自动消失。
 * 不强制跳转——用户点「查看」才按通知携带的落点跳转（[navigateFromNotification]）。
 * 多窗口各自渲染同一全局弹窗，首个倒计时到点即清除，其余窗口随之收起。
 */
@Composable
fun CompletionPopupHost() {
    val popup = NotificationCenter.popup ?: return
    var visible by remember(popup.id) { mutableStateOf(true) }
    val alpha by animateFloatAsState(if (visible) 1f else 0f)
    LaunchedEffect(popup.id) {
        // 多窗口都会起这个计时器，共同消费同一个全局 popup；先到先得，不影响体验
        delay(6000)
        visible = false
        delay(300)
        NotificationCenter.consumePopup()
    }
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.TopEnd) {
        Box(
            Modifier.padding(top = 74.dp, end = 24.dp).widthIn(max = 360.dp).alpha(alpha),
        ) {
            Surface(
                shape = RoundedCornerShape(12.dp),
                elevation = 14.dp,
                color = Color.White,
            ) {
                Column(Modifier.padding(16.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(
                            Icons.Default.CheckCircle,
                            null,
                            tint = Primary,
                            modifier = Modifier.size(20.dp),
                        )
                        Spacer(Modifier.width(8.dp))
                        Text(
                            popup.title,
                            fontSize = 14.sp,
                            fontWeight = FontWeight.SemiBold,
                            color = Ink,
                        )
                        Spacer(Modifier.weight(1f))
                        Icon(
                            Icons.Default.Close,
                            null,
                            tint = Muted,
                            modifier = Modifier.size(16.dp)
                                .clickable { visible = false; NotificationCenter.consumePopup() },
                        )
                    }
                    Spacer(Modifier.height(6.dp))
                    Text(popup.body, fontSize = 12.5.sp, color = Ink2, lineHeight = 18.sp)
                    if (popup.screen != null) {
                        Spacer(Modifier.height(12.dp))
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                            Box(
                                Modifier.clip(RoundedCornerShape(8.dp))
                                    .background(Primary)
                                    .clickable {
                                        navigateFromNotification(popup)
                                        NotificationCenter.consumePopup()
                                    }
                                    .padding(horizontal = 16.dp, vertical = 7.dp),
                            ) {
                                Text("查看", fontSize = 12.5.sp, color = Color.White)
                            }
                        }
                    }
                }
            }
        }
    }
}
