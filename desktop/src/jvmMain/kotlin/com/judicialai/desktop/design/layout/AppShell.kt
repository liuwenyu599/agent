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
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.CropSquare
import androidx.compose.material.icons.filled.FilterNone
import androidx.compose.material.icons.filled.Groups
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.Remove
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
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.app.AppNav
import com.judicialai.desktop.app.AppScreen
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.app.LocalWindowSession
import com.judicialai.desktop.app.NavItem
import com.judicialai.desktop.app.WindowManager
import com.judicialai.desktop.design.components.AppButton
import com.judicialai.desktop.design.components.AppButtonKind
import com.judicialai.desktop.design.components.AppSearchField
import com.judicialai.desktop.design.components.GlobalNavDrawer
import com.judicialai.desktop.design.components.PersonalCenterDrawer
import com.judicialai.desktop.design.theme.AiIndigo
import com.judicialai.desktop.design.theme.AppBg
import com.judicialai.desktop.design.theme.BrandEnd
import com.judicialai.desktop.design.theme.BrandStart
import com.judicialai.desktop.design.theme.Danger
import com.judicialai.desktop.design.theme.Dimens
import com.judicialai.desktop.design.theme.FeatureWriteInk
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
 * - 右：用户身份（第三层；个人中心收在头像下拉里）。
 * 导航只保留左上角抽屉，且与 Header 共用同一套视觉语言。
 *
 * 多窗口：抽屉开合状态按窗口（LocalWindowSession）各自独立；
 * 「新开独立窗口」入口在右上角用户菜单。
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
    val session = LocalWindowSession.current

    Box(Modifier.fillMaxSize().background(AppBg)) {
        Column(Modifier.fillMaxSize()) {
            AppHeader(current = current, username = username, userRole = userRole,
                onLogout = onLogout)
            Box(Modifier.weight(1f).fillMaxWidth()) { content() }
        }

        if (session.navDrawerOpen) {
            GlobalNavDrawer(
                isAdmin = isAdmin,
                onNavigate = onNavigate,
                onHome = onHome,
                onDismiss = { session.navDrawerOpen = false },
            )
        }

        if (session.personalCenterOpen) {
            PersonalCenterDrawer(
                vm = personalVm,
                onDismiss = { session.personalCenterOpen = false },
            )
        }

        if (AppState.guideActive && WindowManager.active === session) {
            UsageGuideOverlay()
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
    val session = LocalWindowSession.current
    // 无边框窗口下由 Header 自绘窗口控制按钮；非无边框环境为 null，自动隐藏
    val chrome = LocalWindowChrome.current

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
                    .clickable { session.navDrawerOpen = true }
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
                onClick = { session.navDrawerOpen = true },
            )

            // 无边框窗口：Header 中间空白区域可拖动窗口（替代系统标题栏拖动）
            Box(
                Modifier.weight(1f).fillMaxHeight()
                    .dragWindow(chrome?.window)
            )

            // ---- 全局搜索 ----
            AppSearchField(
                value = AppState.navQuery,
                onValueChange = { AppState.navQuery = it },
                placeholder = "搜索功能，例如：模板、知识库、PPT",
                modifier = Modifier.width(260.dp),
                onFocusOpen = { session.navDrawerOpen = true },
            )

            Spacer(Modifier.width(Dimens.space4))
            Box(Modifier.width(1.dp).height(24.dp).background(Line))
            Spacer(Modifier.width(Dimens.space4))

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
                        session.personalCenterOpen = true
                    }) { Text("个人中心", fontSize = 13.sp) }
                    // 多开独立窗口：新窗口导航独立，生成任务等全局状态共享，
                    // 一个窗口跑生成时另一个窗口可正常办公
                    DropdownMenuItem(onClick = {
                        userMenuOpen = false
                        WindowManager.openNew()
                    }) { Text("新开独立窗口", fontSize = 13.sp) }
                    if (AppState.isDeveloper) {
                        DropdownMenuItem(onClick = {
                            userMenuOpen = false
                            AppState.navigate(AppScreen.SETTINGS)
                        }) { Text("连接设置", fontSize = 13.sp) }
                    }
                    DropdownMenuItem(onClick = {
                        userMenuOpen = false
                        onLogout()
                    }) { Text("退出登录", fontSize = 13.sp, color = com.judicialai.desktop.design.theme.Danger) }
                }
            }

            // ---- 窗口控制：最小化 / 最大化·还原 / 关闭（无边框窗口自绘）----
            if (chrome != null) {
                Spacer(Modifier.width(Dimens.space3))
                WindowControlGroup(chrome)
            }
        }
            Box(Modifier.fillMaxWidth().height(1.dp).background(Line))
        }
    }
}

/**
 * 窗口控制按钮组（最小化 / 最大化·还原 / 关闭）。
 * 仅在无边框窗口（[LocalWindowChrome] 非空）时显示。
 */
@Composable
private fun WindowControlGroup(actions: WindowChromeActions) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        WindowControlButton(
            icon = Icons.Default.Remove,
            description = "最小化",
            onClick = actions.minimize,
        )
        Spacer(Modifier.width(Dimens.space1))
        WindowControlButton(
            icon = if (actions.maximized) Icons.Default.FilterNone else Icons.Default.CropSquare,
            description = if (actions.maximized) "向下还原" else "最大化",
            onClick = actions.toggleMaximize,
        )
        Spacer(Modifier.width(Dimens.space1))
        WindowControlButton(
            icon = Icons.Default.Close,
            description = "关闭",
            onClick = actions.close,
            hoverBg = Danger,
            hoverTint = Color.White,
            hoverBorder = Danger,
        )
    }
}

/**
 * 单个窗口控制按钮：32dp 方形。
 *
 * 与 Windows 原生标题栏一致——三个按钮**常态可见**，hover 只是「高亮」而非「显形」：
 * 静息态即有淡底 + 浅描边 + 深色图标（与同文件 [HeaderIconButton] 同一套视觉语言），
 * 避免浅灰图标落在白色 Header 上因对比度不足而被认为「按钮没了」。
 *
 * @param restBg 静息态底色（比 hover 更浅，保证 hover 仍有加深反馈）
 * @param restTint 静息态图标色
 * @param restBorder 静息态描边色
 * @param hoverBg 悬停底色
 * @param hoverTint 悬停图标色
 * @param hoverBorder 悬停描边色
 */
@Composable
private fun WindowControlButton(
    icon: ImageVector,
    description: String,
    onClick: () -> Unit,
    restBg: Color = SurfaceTonal,
    restTint: Color = Ink2,
    restBorder: Color = Line,
    hoverBg: Color = SurfaceDeep,
    hoverTint: Color = Ink2,
    hoverBorder: Color = LineStrong,
) {
    val interaction = remember { MutableInteractionSource() }
    val hovered by interaction.collectIsHoveredAsState()
    val shape = RoundedCornerShape(Dimens.radiusSm)
    Box(
        Modifier.size(32.dp).clip(shape)
            .background(if (hovered) hoverBg else restBg)
            .border(1.dp, if (hovered) hoverBorder else restBorder, shape)
            .clickable(interactionSource = interaction, indication = null) { onClick() },
        contentAlignment = Alignment.Center,
    ) {
        Icon(icon, contentDescription = description,
            tint = if (hovered) hoverTint else restTint,
            modifier = Modifier.size(Dimens.iconSm))
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
private fun UsageGuideOverlay() {
    val step = AppState.currentGuideStep ?: return
    Box(
        Modifier.fillMaxSize()
            .background(Color.Black.copy(alpha = 0.38f))
            .clickable(
                interactionSource = remember { MutableInteractionSource() },
                indication = null,
                onClick = {},
            ),
    ) {
        Box(
            Modifier.fillMaxSize()
                .padding(top = Dimens.headerHeight + 14.dp, start = 14.dp, end = 14.dp, bottom = 14.dp)
                .border(2.dp, Primary, RoundedCornerShape(Dimens.radiusLg)),
        )

        Surface(
            modifier = Modifier.align(Alignment.BottomCenter)
                .padding(28.dp).width(560.dp),
            shape = RoundedCornerShape(Dimens.radiusLg),
            color = SurfaceColor,
            elevation = 12.dp,
        ) {
            Column(Modifier.padding(Dimens.space5)) {
                Text(
                    "使用指南  ${AppState.guideIndex + 1} / ${AppState.guideSteps.size}",
                    fontSize = 11.5.sp, color = Primary, fontWeight = FontWeight.SemiBold,
                )
                Spacer(Modifier.height(Dimens.space2))
                Text(step.title, fontSize = 18.sp, fontWeight = FontWeight.SemiBold, color = Ink)
                Spacer(Modifier.height(Dimens.space2))
                Text(step.description, fontSize = 13.sp, color = Ink2, lineHeight = 20.sp)
                Spacer(Modifier.height(Dimens.space2))
                Box(
                    Modifier.fillMaxWidth().clip(RoundedCornerShape(Dimens.radiusSm))
                        .background(Primary.copy(alpha = 0.08f))
                        .padding(Dimens.space3),
                ) {
                    Text("建议操作：${step.actionHint}", fontSize = 12.5.sp,
                        color = Ink2, lineHeight = 19.sp)
                }
                Spacer(Modifier.height(Dimens.space4))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    AppButton(
                        text = "退出指南",
                        onClick = { AppState.stopGuide() },
                        kind = AppButtonKind.SECONDARY,
                    )
                    Spacer(Modifier.weight(1f))
                    AppButton(
                        text = "上一步",
                        onClick = { AppState.previousGuideStep() },
                        enabled = AppState.guideIndex > 0,
                        kind = AppButtonKind.SECONDARY,
                    )
                    Spacer(Modifier.width(Dimens.space2))
                    AppButton(
                        text = if (AppState.guideIndex == AppState.guideSteps.lastIndex)
                            "完成" else "下一步",
                        onClick = { AppState.nextGuideStep() },
                    )
                }
            }
        }
    }
}
