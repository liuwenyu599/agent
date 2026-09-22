package com.judicialai.desktop.design.layout

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsHoveredAsState
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
import androidx.compose.material.Surface
import androidx.compose.material.Text
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AccountBalance
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.Groups
import androidx.compose.material.icons.filled.Menu
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.app.AppNav
import com.judicialai.desktop.app.AppScreen
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.app.NavItem
import com.judicialai.desktop.design.components.AppSearchField
import com.judicialai.desktop.design.components.GlobalNavDrawer
import com.judicialai.desktop.design.components.PersonalCenterDrawer
import com.judicialai.desktop.design.theme.AiIndigo
import com.judicialai.desktop.design.theme.AppBg
import com.judicialai.desktop.design.theme.BrandEnd
import com.judicialai.desktop.design.theme.BrandStart
import com.judicialai.desktop.design.theme.Dimens
import com.judicialai.desktop.design.theme.FeatureWriteInk
import com.judicialai.desktop.design.theme.FeatureWriteSoft
import com.judicialai.desktop.design.theme.Ink
import com.judicialai.desktop.design.theme.Ink2
import com.judicialai.desktop.design.theme.Line
import com.judicialai.desktop.design.theme.LineStrong
import com.judicialai.desktop.design.theme.Muted
import com.judicialai.desktop.design.theme.Muted2
import com.judicialai.desktop.design.theme.OnPrimaryText
import com.judicialai.desktop.design.theme.Primary
import com.judicialai.desktop.design.theme.Surface as SurfaceColor
import com.judicialai.desktop.design.theme.SurfaceDeep
import com.judicialai.desktop.design.theme.SurfaceTonal
import com.judicialai.desktop.features.personal.PersonalViewModel

/**
 * 应用外壳（v4.0）
 *
 * Header 是稳定的品牌框架，不再是「一堆文字横向排开的后台导航条」：
 * - 左：品牌徽标 + 平台名（第一层）→ 当前业务位置（第二层）；
 * - 中：全局搜索（胶囊、弱底，不抢主权重）；
 * - 右：必要状态 → 用户身份（第三层；个人中心收在头像下拉里）。
 * 导航只保留左上角抽屉，且与 Header 共用同一套视觉语言。
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
                onLogout = onLogout)
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
    onLogout: () -> Unit,
) {
    var userMenuOpen by remember { mutableStateOf(false) }
    val group = AppNav.groupOf(current)

    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = SurfaceColor,
        elevation = Dimens.elevCard,
    ) {
        Column {
        Row(
            Modifier.fillMaxWidth().height(Dimens.headerHeight)
                .padding(horizontal = Dimens.space5),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            // ---- 品牌区：徽标 + 平台名 + 当前业务位置 ----
            Row(
                Modifier.clip(RoundedCornerShape(Dimens.radiusMd))
                    .clickable { AppState.navDrawerOpen = true }
                    .padding(horizontal = Dimens.space2, vertical = Dimens.space1 + 2.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(
                    Modifier.size(36.dp).clip(RoundedCornerShape(Dimens.radiusControl))
                        .background(Brush.linearGradient(listOf(BrandStart, BrandEnd))),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(Icons.Default.AccountBalance, contentDescription = null,
                        tint = OnPrimaryText, modifier = Modifier.size(Dimens.iconMd))
                }
                Spacer(Modifier.width(Dimens.space3))
                Column {
                    Text("白云司法局智慧办公平台", fontSize = 14.5.sp,
                        fontWeight = FontWeight.SemiBold, color = Ink, letterSpacing = 0.1.sp)
                    Spacer(Modifier.height(1.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            if (current == AppScreen.HOME) "工作台"
                            else "${group?.title ?: "业务"} · ${current.title}",
                            fontSize = 11.5.sp, color = Muted,
                        )
                        val dept = AppState.departmentName
                        if (dept.isNotBlank()) {
                            Spacer(Modifier.width(Dimens.space2))
                            Box(Modifier.size(3.dp).clip(CircleShape).background(LineStrong))
                            Spacer(Modifier.width(Dimens.space2))
                            Icon(Icons.Default.Groups, contentDescription = null,
                                tint = FeatureWriteInk, modifier = Modifier.size(12.dp))
                            Spacer(Modifier.width(3.dp))
                            Text(dept, fontSize = 11.5.sp, color = FeatureWriteInk,
                                fontWeight = FontWeight.Medium)
                        }
                    }
                }
                Spacer(Modifier.width(Dimens.space2))
                Icon(Icons.Default.ArrowDropDown, contentDescription = "打开全局导航",
                    tint = Muted, modifier = Modifier.size(Dimens.iconLg))
            }

            Spacer(Modifier.width(Dimens.space2))

            // 导航入口按钮：与品牌区相邻，保证可发现性
            HeaderIconButton(
                icon = Icons.Default.Menu,
                description = "打开全局导航",
                onClick = { AppState.navDrawerOpen = true },
            )

            Spacer(Modifier.weight(1f))

            // ---- 全局搜索 ----
            AppSearchField(
                value = AppState.navQuery,
                onValueChange = { AppState.navQuery = it },
                placeholder = "搜索功能，例如：模板、审批、PPT",
                modifier = Modifier.width(260.dp),
                onFocusOpen = { AppState.navDrawerOpen = true },
            )

            Spacer(Modifier.width(Dimens.space4))
            Box(Modifier.width(1.dp).height(24.dp).background(Line))
            Spacer(Modifier.width(Dimens.space4))

            // ---- 必要状态：待办 ----
            if (AppState.todoCount > 0) {
                HeaderStatusPill("${AppState.todoCount} 项待办")
                Spacer(Modifier.width(Dimens.space2))
            }

            // ---- 用户身份 ----
            Box {
                Row(
                    Modifier.clip(RoundedCornerShape(Dimens.radiusControl))
                        .clickable { userMenuOpen = true }
                        .padding(horizontal = Dimens.space2, vertical = Dimens.space1 + 2.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Box(
                        Modifier.size(32.dp).clip(CircleShape)
                            .background(Brush.linearGradient(listOf(AiIndigo, Primary))),
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
                    Spacer(Modifier.width(Dimens.space1))
                    Icon(Icons.Default.ArrowDropDown, contentDescription = null,
                        tint = Muted2, modifier = Modifier.size(Dimens.iconMd))
                }
                DropdownMenu(expanded = userMenuOpen,
                    onDismissRequest = { userMenuOpen = false }) {
                    // 个人中心入口收在头像下拉里（Header 不再单独放按钮）
                    DropdownMenuItem(onClick = {
                        userMenuOpen = false
                        AppState.personalCenterOpen = true
                    }) { Text("个人中心", fontSize = 13.sp) }
                    DropdownMenuItem(onClick = {
                        userMenuOpen = false
                        AppState.navigate(AppScreen.SETTINGS)
                    }) { Text("服务器连接设置", fontSize = 13.sp) }
                    DropdownMenuItem(onClick = {
                        userMenuOpen = false
                        onLogout()
                    }) { Text("退出登录", fontSize = 13.sp, color = com.judicialai.desktop.design.theme.Danger) }
                }
            }
        }
            Box(Modifier.fillMaxWidth().height(1.dp).background(Line))
        }
    }
}

@Composable
private fun HeaderIconButton(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    description: String,
    onClick: () -> Unit,
    size: Dp = 36.dp,
) {
    val interaction = remember { MutableInteractionSource() }
    val hovered by interaction.collectIsHoveredAsState()
    Box(
        Modifier.size(size).clip(RoundedCornerShape(Dimens.radiusControl))
            .background(if (hovered) SurfaceDeep else SurfaceTonal)
            .border(1.dp, if (hovered) LineStrong else Line,
                RoundedCornerShape(Dimens.radiusControl))
            .clickable(interactionSource = interaction, indication = null) { onClick() },
        contentAlignment = Alignment.Center,
    ) {
        Icon(icon, contentDescription = description, tint = Ink2,
            modifier = Modifier.size(Dimens.iconMd))
    }
}

@Composable
private fun HeaderStatusPill(text: String) {
    Box(
        Modifier.clip(RoundedCornerShape(Dimens.radiusPill))
            .background(com.judicialai.desktop.design.theme.AmberSoft)
            .border(1.dp, com.judicialai.desktop.design.theme.AmberLine,
                RoundedCornerShape(Dimens.radiusPill))
            .padding(horizontal = 10.dp, vertical = 5.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(text, fontSize = 11.5.sp,
            color = com.judicialai.desktop.design.theme.AmberInk,
            fontWeight = FontWeight.Medium)
    }
}
