package com.judicialai.desktop.design.components

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.Icon
import androidx.compose.material.Text
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AccountCircle
import androidx.compose.material.icons.filled.ExitToApp
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.app.AppMenu
import com.judicialai.desktop.app.AppScreen
import com.judicialai.desktop.design.theme.SidebarActive
import com.judicialai.desktop.design.theme.SidebarBg
import com.judicialai.desktop.design.theme.SidebarBorder
import com.judicialai.desktop.design.theme.SidebarHover
import com.judicialai.desktop.design.theme.SidebarSubText
import com.judicialai.desktop.design.theme.SidebarText

/**
 * 侧边栏：1:1 还原 Web 端 AppLayout.vue
 * 深色 #16223f，展开 220px / 折叠 64px，菜单项高 44px、圆角 8px、左右边距 10px，
 * 选中 #2f5cff 白色加粗，hover rgba(255,255,255,0.08)。
 */
@Composable
fun AppSidebar(
    current: AppScreen,
    collapsed: Boolean,
    username: String,
    userRole: String,
    isAdmin: Boolean,
    onNavigate: (AppScreen) -> Unit,
    onLogout: () -> Unit,
) {
    Column(
        Modifier.width(if (collapsed) 64.dp else 220.dp)
            .fillMaxHeight()
            .background(SidebarBg),
    ) {
        // Logo 区：高 64px，底部 1px 分隔
        Row(
            Modifier.fillMaxWidth().height(64.dp).padding(horizontal = 16.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Icon(Icons.Default.AccountCircle, contentDescription = null,
                tint = Color.White, modifier = Modifier.size(26.dp))
            if (!collapsed) {
                Column {
                    Text("司法智能办公平台", color = Color.White,
                        fontSize = 15.sp, fontWeight = FontWeight.SemiBold, maxLines = 1,
                        overflow = TextOverflow.Ellipsis)
                    Text("智能 · 高效 · 安全", color = SidebarSubText, fontSize = 11.sp)
                }
            }
        }
        Box(Modifier.fillMaxWidth().height(1.dp).background(SidebarBorder))

        // 菜单
        Column(
            Modifier.weight(1f).verticalScroll(rememberScrollState())
                .padding(vertical = 10.dp),
        ) {
            for (entry in AppMenu.entries) {
                if (entry.adminOnly && !isAdmin) continue
                if (entry.screen != null) {
                    SidebarItem(
                        label = entry.label,
                        icon = entry.icon,
                        selected = current == entry.screen,
                        collapsed = collapsed,
                        indent = false,
                        onClick = { onNavigate(entry.screen) },
                    )
                } else {
                    // 分组（智能写作）：组标题不可跳转，子项缩进
                    val groupActive = entry.children.contains(current)
                    SidebarItem(
                        label = entry.label,
                        icon = entry.icon,
                        selected = false,
                        collapsed = collapsed,
                        indent = false,
                        onClick = { if (collapsed) onNavigate(entry.children.first()) },
                    )
                    if (!collapsed) {
                        for (child in entry.children) {
                            SidebarItem(
                                label = child.title,
                                icon = null,
                                selected = current == child,
                                collapsed = false,
                                indent = true,
                                onClick = { onNavigate(child) },
                            )
                        }
                    } else if (groupActive) {
                        // 折叠态下分组高亮由组标题承担
                    }
                }
            }
        }

        // 底部用户区
        if (!collapsed) {
            Box(Modifier.fillMaxWidth().height(1.dp).background(SidebarBorder))
            Column(Modifier.padding(14.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Box(
                        Modifier.size(32.dp).clip(CircleShape).background(SidebarActive),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(username.take(1).uppercase(), color = Color.White,
                            fontSize = 14.sp, fontWeight = FontWeight.Bold)
                    }
                    Column(Modifier.weight(1f)) {
                        Text(username, color = Color.White, fontSize = 14.sp,
                            fontWeight = FontWeight.Medium, maxLines = 1,
                            overflow = TextOverflow.Ellipsis)
                        Text(userRole, color = SidebarSubText, fontSize = 12.sp)
                    }
                }
                Spacer(Modifier.height(10.dp))
                Row(
                    Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp))
                        .clickable(onClick = onLogout)
                        .padding(vertical = 8.dp),
                    horizontalArrangement = Arrangement.Center,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(Icons.Default.ExitToApp, contentDescription = null,
                        tint = SidebarText, modifier = Modifier.size(16.dp))
                    Spacer(Modifier.width(6.dp))
                    Text("退出", color = SidebarText, fontSize = 13.sp)
                }
            }
        }
    }
}

@Composable
private fun SidebarItem(
    label: String,
    icon: androidx.compose.ui.graphics.vector.ImageVector?,
    selected: Boolean,
    collapsed: Boolean,
    indent: Boolean,
    onClick: () -> Unit,
) {
    Row(
        Modifier.fillMaxWidth()
            .padding(horizontal = 10.dp, vertical = 2.dp)
            .height(44.dp)
            .clip(RoundedCornerShape(8.dp))
            .background(
                if (selected) SidebarActive
                else Color.Transparent,
            )
            .clickable(onClick = onClick)
            .padding(start = if (indent) 38.dp else if (collapsed) 0.dp else 14.dp,
                end = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = if (collapsed && !indent) Arrangement.Center else Arrangement.Start,
    ) {
        if (icon != null) {
            Icon(icon, contentDescription = label,
                tint = if (selected) Color.White else SidebarText,
                modifier = Modifier.size(18.dp))
            if (!collapsed) Spacer(Modifier.width(10.dp))
        }
        if (!collapsed) {
            Text(
                label,
                color = if (selected) Color.White else SidebarText,
                fontSize = 14.sp,
                fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

