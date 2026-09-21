package com.judicialai.desktop.design.layout

import androidx.compose.foundation.background
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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.DropdownMenu
import androidx.compose.material.DropdownMenuItem
import androidx.compose.material.Icon
import androidx.compose.material.OutlinedTextField
import androidx.compose.material.Text
import androidx.compose.material.TextFieldDefaults
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AccountBalance
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.Groups
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Search
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.app.AppNav
import com.judicialai.desktop.app.AppScreen
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.app.NavItem
import com.judicialai.desktop.design.components.GlobalNavDrawer
import com.judicialai.desktop.design.components.PersonalCenterDrawer
import com.judicialai.desktop.features.personal.PersonalViewModel
import com.judicialai.desktop.design.theme.AppBg
import com.judicialai.desktop.design.theme.Dimens
import com.judicialai.desktop.design.theme.Ink
import com.judicialai.desktop.design.theme.Ink2
import com.judicialai.desktop.design.theme.Line
import com.judicialai.desktop.design.theme.Muted
import com.judicialai.desktop.design.theme.OnPrimaryText
import com.judicialai.desktop.design.theme.Primary
import com.judicialai.desktop.design.theme.Surface

/**
 * 应用外壳（v3.2）
 *
 * - 删除常驻左侧栏：导航统一收进左上角「导航抽屉」，页面内容占满宽度；
 * - 顶部轻量 Header：品牌名（点击打开全局导航）+ 当前科室/助手 + 搜索 + 待办 + 用户；
 * - 面包屑只在非 HOME 页面出现，指明当前位置。
 */
@Composable
fun AppShell(
    current: AppScreen,
    username: String,
    userRole: String,
    isAdmin: Boolean,
    onNavigate: (NavItem) -> Unit,
    onHome: () -> Unit,
    onLogout: () -> Unit,
    content: @Composable () -> Unit,
) {
    val personalVm: PersonalViewModel = remember { PersonalViewModel() }

    Box(Modifier.fillMaxSize().background(AppBg)) {
        Column(Modifier.fillMaxSize()) {
            AppHeader(current = current, username = username, userRole = userRole,
                onHome = onHome, onLogout = onLogout)
            Box(Modifier.fillMaxWidth().height(1.dp).background(Line))
            Box(Modifier.weight(1f).fillMaxWidth()) { content() }
        }

        if (AppState.navDrawerOpen) {
            GlobalNavDrawer(
                isAdmin = isAdmin,
                onNavigate = onNavigate,
                onHome = onHome,
                onDismiss = { AppState.navDrawerOpen = false },
            )
        }

        if (AppState.personalCenterOpen) {
            PersonalCenterDrawer(
                vm = personalVm,
                onDismiss = { AppState.personalCenterOpen = false },
            )
        }
    }
}

@Composable
private fun AppHeader(
    current: AppScreen,
    username: String,
    userRole: String,
    onHome: () -> Unit,
    onLogout: () -> Unit,
) {
    var userMenuOpen by remember { mutableStateOf(false) }
    val group = AppNav.groupOf(current)

    Row(
        Modifier.fillMaxWidth().height(Dimens.headerHeight).background(Surface)
            .padding(horizontal = Dimens.space5),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        // 品牌名：点击打开全局导航
        Row(
            Modifier.clip(RoundedCornerShape(Dimens.radiusSm))
                .clickable { AppState.navDrawerOpen = true }
                .padding(horizontal = Dimens.space2, vertical = Dimens.space2),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(Icons.Default.AccountBalance, contentDescription = null,
                tint = Primary, modifier = Modifier.size(22.dp))
            Spacer(Modifier.width(Dimens.space2))
            Text("白云司法局智慧办公平台", fontSize = 15.sp,
                fontWeight = FontWeight.SemiBold, color = Ink)
            Spacer(Modifier.width(Dimens.space1))
            Icon(Icons.Default.ArrowDropDown, contentDescription = "打开全局导航",
                tint = Muted, modifier = Modifier.size(18.dp))
        }

        // 当前位置（面包屑）：只在非工作台页面出现，指明所在位置
        if (current != AppScreen.HOME) {
            Spacer(Modifier.width(Dimens.space4))
            Box(Modifier.width(1.dp).height(20.dp).background(Line))
            Spacer(Modifier.width(Dimens.space4))
            Text(group?.title ?: "业务", fontSize = 12.5.sp, color = Muted)
            Spacer(Modifier.width(Dimens.space2))
            Text("›", fontSize = 12.5.sp, color = Muted)
            Spacer(Modifier.width(Dimens.space2))
            Text(current.title, fontSize = 13.5.sp, fontWeight = FontWeight.SemiBold,
                color = Ink)
        }

        // 当前科室 / 本科室助手：常驻顶栏，说明本次办公所处的科室上下文
        val dept = AppState.departmentName
        if (dept.isNotBlank()) {
            Spacer(Modifier.width(Dimens.space4))
            Row(
                Modifier.clip(RoundedCornerShape(Dimens.radiusPill))
                    .background(com.judicialai.desktop.design.theme.FeatureWriteSoft)
                    .padding(horizontal = 10.dp, vertical = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(Icons.Default.Groups, contentDescription = null,
                    tint = com.judicialai.desktop.design.theme.FeatureWriteInk,
                    modifier = Modifier.size(Dimens.iconSm))
                Spacer(Modifier.width(Dimens.space1))
                Text(dept, fontSize = 12.sp,
                    color = com.judicialai.desktop.design.theme.FeatureWriteInk,
                    fontWeight = FontWeight.Medium)
                if (AppState.agentName.isNotBlank()) {
                    Spacer(Modifier.width(Dimens.space2))
                    Box(Modifier.width(1.dp).height(11.dp)
                        .background(com.judicialai.desktop.design.theme.FeatureWriteInk
                            .copy(alpha = 0.3f)))
                    Spacer(Modifier.width(Dimens.space2))
                    Text(AppState.agentName, fontSize = 12.sp,
                        color = com.judicialai.desktop.design.theme.FeatureWriteInk)
                }
            }
        }

        Spacer(Modifier.weight(1f))

        // 导航搜索：真实过滤导航项，不做假数据检索
        OutlinedTextField(
            value = AppState.navQuery,
            onValueChange = {
                AppState.navQuery = it
                AppState.navDrawerOpen = true
            },
            placeholder = { Text("搜索功能", fontSize = 12.5.sp, color = Muted) },
            leadingIcon = { Icon(Icons.Default.Search, null, tint = Muted,
                modifier = Modifier.size(Dimens.iconMd)) },
            singleLine = true,
            modifier = Modifier.width(220.dp).height(40.dp),
            colors = TextFieldDefaults.outlinedTextFieldColors(
                focusedBorderColor = Primary, cursorColor = Primary, unfocusedBorderColor = Line),
        )

        Spacer(Modifier.width(Dimens.space3))

        // 个人中心：待办、最近使用、我的文档、我的审批、收藏与设置（徽标为后端真实待办数）
        Box(
            Modifier.clip(RoundedCornerShape(Dimens.radiusSm))
                .clickable { AppState.personalCenterOpen = true }
                .padding(horizontal = Dimens.space3, vertical = Dimens.space2),
            contentAlignment = Alignment.Center,
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Default.Person, contentDescription = null,
                    tint = Ink2, modifier = Modifier.size(Dimens.iconMd))
                Spacer(Modifier.width(Dimens.space2))
                Text("个人中心", fontSize = 13.sp, color = Ink2)
                if (AppState.todoCount > 0) {
                    Spacer(Modifier.width(Dimens.space2))
                    Box(
                        Modifier.clip(RoundedCornerShape(Dimens.radiusPill))
                            .background(com.judicialai.desktop.design.theme.Accent)
                            .padding(horizontal = 6.dp, vertical = 1.dp),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text("${AppState.todoCount}", fontSize = 11.sp, color = OnPrimaryText,
                            fontWeight = FontWeight.SemiBold)
                    }
                }
            }
        }

        Spacer(Modifier.width(Dimens.space2))

        // 用户
        Box {
            Row(
                Modifier.clip(RoundedCornerShape(Dimens.radiusSm))
                    .clickable { userMenuOpen = true }
                    .padding(horizontal = Dimens.space2, vertical = Dimens.space2),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(
                    Modifier.size(30.dp).clip(CircleShape).background(Primary),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(username.take(1).uppercase(), color = OnPrimaryText,
                        fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
                }
                Spacer(Modifier.width(Dimens.space2))
                Column {
                    Text(username, fontSize = 13.sp, color = Ink,
                        fontWeight = FontWeight.Medium)
                    Text(userRole, fontSize = 11.sp, color = Muted)
                }
            }
            DropdownMenu(expanded = userMenuOpen,
                onDismissRequest = { userMenuOpen = false }) {
                DropdownMenuItem(onClick = {
                    userMenuOpen = false
                    AppState.navigate(AppScreen.SETTINGS)
                }) { Text("服务器连接设置", fontSize = 13.sp) }
                DropdownMenuItem(onClick = {
                    userMenuOpen = false
                    onLogout()
                }) { Text("退出登录", fontSize = 13.sp) }
            }
        }
    }
}
