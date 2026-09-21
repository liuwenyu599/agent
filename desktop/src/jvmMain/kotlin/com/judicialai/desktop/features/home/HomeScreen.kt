package com.judicialai.desktop.features.home

import androidx.compose.animation.core.animateDpAsState
import androidx.compose.foundation.background
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
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.Card
import androidx.compose.material.Icon
import androidx.compose.material.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.app.AppNav
import com.judicialai.desktop.app.AppScreen
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.app.NavItem
import com.judicialai.desktop.design.components.EmptyState
import com.judicialai.desktop.design.components.SectionTitle
import com.judicialai.desktop.design.components.SoftPanel
import com.judicialai.desktop.design.components.StatusChip
import com.judicialai.desktop.design.components.paletteOf
import com.judicialai.desktop.design.theme.AppBg
import com.judicialai.desktop.design.theme.Dimens
import com.judicialai.desktop.design.theme.FeatureCheckSoft
import com.judicialai.desktop.design.theme.FeaturePptSoft
import com.judicialai.desktop.design.theme.FeatureTemplateSoft
import com.judicialai.desktop.design.theme.FeatureWriteInk
import com.judicialai.desktop.design.theme.FeatureWriteSoft
import com.judicialai.desktop.design.theme.HomeBg
import com.judicialai.desktop.design.theme.Ink
import com.judicialai.desktop.design.theme.Ink2
import com.judicialai.desktop.design.theme.Line
import com.judicialai.desktop.design.theme.Muted
import com.judicialai.desktop.design.theme.Ok
import com.judicialai.desktop.design.theme.OkSoft
import com.judicialai.desktop.design.theme.Surface
import com.judicialai.desktop.design.theme.Warn
import com.judicialai.desktop.design.theme.WarnSoft
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.util.Locale

private val WEEKDAYS = arrayOf("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")

/**
 * 工作台（HOME）
 *
 * 产品定位：办公工具的首页，不是管理后台 Dashboard。
 * 结构 = 大欢迎区 + 2×2 四张整卡彩色功能卡 + 弱化的二级区（最近使用 / 我的待办）。
 * 默认无侧边导航；所有数据来自后端，无占位假数据。
 */
@Composable
fun HomeScreen(vm: HomeViewModel = remember { HomeViewModel() }) {
    Column(
        Modifier.fillMaxSize().background(HomeBg).verticalScroll(rememberScrollState())
            .padding(horizontal = Dimens.space10, vertical = Dimens.space8),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Box(Modifier.widthIn(max = Dimens.homeMaxWidth)) {
            Column(verticalArrangement = Arrangement.spacedBy(Dimens.space8)) {
                WelcomeBlock(vm)
                FeatureGrid()
            }
        }
    }
}

// ---------------- 欢迎区 ----------------

@Composable
private fun WelcomeBlock(vm: HomeViewModel) {
    val today = LocalDate.now()
    val dateText = today.format(DateTimeFormatter.ofPattern("yyyy年M月d日")) +
        "  " + WEEKDAYS[(today.dayOfWeek.value + 6) % 7]

    Column(Modifier.fillMaxWidth()) {
        Text("${vm.greeting}，${vm.realName.ifBlank { AppState.displayName }}",
            fontSize = 28.sp, fontWeight = FontWeight.SemiBold, color = Ink)
        Spacer(Modifier.height(Dimens.space2))
        Text("今天有什么需要处理？", fontSize = 15.sp, color = Ink2)
        Spacer(Modifier.height(Dimens.space3))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(dateText, fontSize = 12.5.sp, color = Muted)
            if (vm.department.isNotBlank()) {
                Spacer(Modifier.width(Dimens.space3))
                Text(vm.department, fontSize = 12.5.sp, color = Muted)
            }
            if (vm.roleName.isNotBlank()) {
                Spacer(Modifier.width(Dimens.space3))
                Text(vm.roleName, fontSize = 12.5.sp, color = Muted)
            }
            if (AppState.agentName.isNotBlank()) {
                Spacer(Modifier.width(Dimens.space3))
                Box(
                    Modifier.clip(RoundedCornerShape(Dimens.radiusPill))
                        .background(FeatureWriteSoft)
                        .padding(horizontal = 9.dp, vertical = 3.dp),
                ) {
                    Text(AppState.agentName, fontSize = 12.sp, color = FeatureWriteInk,
                        fontWeight = FontWeight.Medium)
                }
            }
            Spacer(Modifier.width(Dimens.space3))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(6.dp).clip(CircleShape)
                    .background(if (vm.aiOnline) Ok else Muted))
                Spacer(Modifier.width(Dimens.space2))
                Text(if (vm.aiOnline) "AI 助手在线" else "AI 助手离线 · 基础功能正常",
                    fontSize = 12.5.sp, color = Muted)
            }
            if (vm.todoCount > 0) {
                Spacer(Modifier.width(Dimens.space3))
                Text("${vm.todoCount} 项待办", fontSize = 12.5.sp, color = Warn,
                    fontWeight = FontWeight.Medium)
            }
        }
    }
}

// ---------------- 2×2 四大功能卡 ----------------

@Composable
private fun FeatureGrid() {
    val items = AppNav.coreItems
    Column(verticalArrangement = Arrangement.spacedBy(Dimens.space5)) {
        items.chunked(2).forEach { row ->
            Row(horizontalArrangement = Arrangement.spacedBy(Dimens.space5)) {
                row.forEach { item ->
                    FeatureCard(item, Modifier.weight(1f))
                }
            }
        }
    }
}

@Composable
private fun FeatureCard(item: NavItem, modifier: Modifier = Modifier) {
    val palette = paletteOf(item.screen)
    val interaction = remember { MutableInteractionSource() }
    val hovered by interaction.collectIsHoveredAsState()
    val lift by animateDpAsState(if (hovered) (-3).dp else 0.dp)
    val elevation by animateDpAsState(if (hovered) Dimens.elevFloat else Dimens.elevCard)
    val arrow by animateDpAsState(if (hovered) 6.dp else 0.dp)

    Card(
        modifier = modifier.height(196.dp).offset(y = lift),
        shape = RoundedCornerShape(Dimens.radiusXl),
        elevation = elevation,
        backgroundColor = Color.Transparent,
    ) {
        Box(
            Modifier.fillMaxSize()
                .background(Brush.linearGradient(listOf(palette.start, palette.end)))
                .clickable(interactionSource = interaction, indication = null) {
                    AppState.navigate(item.screen, item.adminTab)
                }
                .padding(Dimens.space6),
        ) {
            // 半透明几何装饰：右上角大圆 + 右下角大图标水印
            Box(
                Modifier.size(150.dp).align(Alignment.TopEnd)
                    .offset(x = 40.dp, y = (-52).dp)
                    .clip(CircleShape).background(Color.White.copy(alpha = 0.10f)),
            )
            Icon(
                item.icon, contentDescription = null,
                tint = Color.White.copy(alpha = 0.14f),
                modifier = Modifier.size(Dimens.iconDeco).align(Alignment.BottomEnd)
                    .offset(x = 14.dp, y = 22.dp),
            )

            Column(Modifier.fillMaxSize()) {
                Box(
                    Modifier.size(Dimens.iconFeature).clip(RoundedCornerShape(Dimens.radiusMd))
                        .background(Color.White.copy(alpha = 0.18f)),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(item.icon, contentDescription = null, tint = Color.White,
                        modifier = Modifier.size(Dimens.iconLg))
                }
                Spacer(Modifier.weight(1f))
                Text(item.label, fontSize = 21.sp, fontWeight = FontWeight.SemiBold,
                    color = Color.White, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Spacer(Modifier.height(Dimens.space2))
                Text(item.desc, fontSize = 13.sp, color = Color.White.copy(alpha = 0.88f),
                    maxLines = 1, overflow = TextOverflow.Ellipsis)
                Spacer(Modifier.height(Dimens.space4))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("开始使用", fontSize = 12.5.sp,
                        color = Color.White.copy(alpha = 0.92f),
                        fontWeight = FontWeight.Medium)
                    Spacer(Modifier.width(Dimens.space2))
                    Text("→", fontSize = 14.sp, color = Color.White,
                        modifier = Modifier.offset(x = arrow))
                }
            }
        }
    }
}

// ---------------- 二级区已移除 ----------------
// 「最近使用 / 我的待办」不再占用 HOME 版面，全部收进右上角「个人中心」，
// 保证 2×2 四张彩色功能卡是 HOME 唯一的视觉中心。


/** 首页四卡对应功能色（供其他页面复用：工作区标题底色等） */
fun softColorOf(screen: AppScreen): Color = when (screen) {
    AppScreen.WRITING -> FeatureWriteSoft
    AppScreen.TEMPLATES -> FeatureTemplateSoft
    AppScreen.PPT -> FeaturePptSoft
    AppScreen.FORMAT_CHECK -> FeatureCheckSoft
    else -> AppBg
}
