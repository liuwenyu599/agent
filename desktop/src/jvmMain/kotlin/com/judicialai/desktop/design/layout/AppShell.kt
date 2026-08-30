package com.judicialai.desktop.design.layout

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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.DropdownMenu
import androidx.compose.material.DropdownMenuItem
import androidx.compose.material.Icon
import androidx.compose.material.IconButton
import androidx.compose.material.Text
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.KeyboardArrowLeft
import androidx.compose.material.icons.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.app.AppMenu
import com.judicialai.desktop.app.AppScreen
import com.judicialai.desktop.design.components.AppSidebar
import com.judicialai.desktop.design.theme.MainBg
import com.judicialai.desktop.design.theme.SidebarActive
import com.judicialai.desktop.design.theme.Surface
import com.judicialai.desktop.design.theme.TextPrimary
import com.judicialai.desktop.design.theme.TextRegular
import com.judicialai.desktop.design.theme.TopbarBorder

/**
 * 应用外壳：1:1 还原 Web 端 AppLayout.vue
 * 深色侧边栏 + 56px 白顶栏（折叠按钮 + 页面标题 + 用户下拉）+ #f0f2f5 主区。
 */
@Composable
fun AppShell(
    current: AppScreen,
    username: String,
    userRole: String,
    isAdmin: Boolean,
    onNavigate: (AppScreen) -> Unit,
    onLogout: () -> Unit,
    content: @Composable () -> Unit,
) {
    var collapsed by remember { mutableStateOf(false) }
    var userMenuOpen by remember { mutableStateOf(false) }

    Row(Modifier.fillMaxSize().background(MainBg)) {
        AppSidebar(
            current = current,
            collapsed = collapsed,
            username = username,
            userRole = userRole,
            isAdmin = isAdmin,
            onNavigate = onNavigate,
            onLogout = onLogout,
        )
        Column(Modifier.weight(1f).fillMaxHeight()) {
            // 顶栏：56px 白底
            Row(
                Modifier.fillMaxWidth().height(56.dp).background(Surface)
                    .padding(horizontal = 16.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                IconButton(onClick = { collapsed = !collapsed }) {
                    Icon(
                        if (collapsed) Icons.Default.KeyboardArrowRight
                        else Icons.Default.KeyboardArrowLeft,
                        contentDescription = "折叠菜单", tint = TextRegular,
                    )
                }
                Text(AppMenu.titleOf(current), fontSize = 15.sp,
                    fontWeight = FontWeight.SemiBold, color = TextPrimary)
                Spacer(Modifier.weight(1f))
                Icon(
                    Icons.Default.Notifications, contentDescription = null,
                    tint = TextRegular, modifier = Modifier.size(18.dp),
                )
                Box {
                    Row(
                        Modifier.clip(RoundedCornerShape(8.dp))
                            .clickable { userMenuOpen = true }
                            .padding(horizontal = 8.dp, vertical = 6.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Box(
                            Modifier.size(28.dp).clip(CircleShape).background(SidebarActive),
                            contentAlignment = Alignment.Center,
                        ) {
                            Text(username.take(1).uppercase(), color = Surface,
                                fontSize = 12.sp, fontWeight = FontWeight.Bold)
                        }
                        Text(username, fontSize = 14.sp, color = TextPrimary)
                    }
                    DropdownMenu(expanded = userMenuOpen,
                        onDismissRequest = { userMenuOpen = false }) {
                        DropdownMenuItem(onClick = {
                            userMenuOpen = false
                            onNavigate(AppScreen.SETTINGS)
                        }) { Text("服务器连接设置") }
                        DropdownMenuItem(onClick = {
                            userMenuOpen = false
                            onLogout()
                        }) { Text("退出登录") }
                    }
                }
            }
            Box(Modifier.fillMaxWidth().height(1.dp).background(TopbarBorder))
            Box(Modifier.weight(1f).fillMaxWidth().background(MainBg)) {
                content()
            }
        }
    }
}

