package com.judicialai.desktop.features.home

import androidx.compose.animation.core.animateDpAsState
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
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.Icon
import androidx.compose.material.Surface
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
import com.judicialai.desktop.design.components.FilterChip
import com.judicialai.desktop.design.components.paletteOf
import com.judicialai.desktop.design.theme.AiInk
import com.judicialai.desktop.design.theme.AiSoft
import com.judicialai.desktop.design.theme.AppBg
import com.judicialai.desktop.design.theme.Dimens
import com.judicialai.desktop.design.theme.FeatureCheckSoft
import com.judicialai.desktop.design.theme.FeaturePptSoft
import com.judicialai.desktop.design.theme.FeatureTemplateSoft
import com.judicialai.desktop.design.theme.FeatureWriteSoft
import com.judicialai.desktop.design.theme.Ink
import com.judicialai.desktop.design.theme.Ink2
import com.judicialai.desktop.design.theme.Line
import com.judicialai.desktop.design.theme.Muted
import com.judicialai.desktop.design.theme.Ok
import com.judicialai.desktop.design.theme.Surface as SurfaceColor
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.util.Locale

private val WEEKDAYS = arrayOf("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")

/**
 * 工作台（HOME · v4.0）
 *
 * 结构 = 欢迎条（无背景，页面底色 + 科室上下文） + 2×2 彩色功能卡。
 * 四大功能卡是唯一的视觉中心，不再有二级内容区抢权重。
 */
@Composable
fun HomeScreen(vm: HomeViewModel = remember { HomeViewModel() }) {
    Column(
        Modifier.fillMaxSize().background(AppBg).verticalScroll(rememberScrollState())
            .padding(horizontal = Dimens.space8, vertical = Dimens.space5),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        // 首页 2×2 收窄：局部宽度，不动 Dimens.homeMaxWidth 全局 token
        Box(Modifier.widthIn(max = HOME_CONTENT_MAX_WIDTH)) {
            Column(verticalArrangement = Arrangement.spacedBy(Dimens.space5)) {
                WelcomeBand(vm)
                FeatureGrid()
            }
        }
    }
}

/** 首页内容最大宽：比全局 homeMaxWidth 更窄，让 2×2 格子更紧凑 */
private val HOME_CONTENT_MAX_WIDTH = 960.dp

// ---------------- 欢迎条（无背景，页面底色） ----------------

@Composable
private fun WelcomeBand(vm: HomeViewModel) {
    val today = LocalDate.now()
    val dateText = today.format(DateTimeFormatter.ofPattern("yyyy年M月d日")) +
        "  " + WEEKDAYS[(today.dayOfWeek.value + 6) % 7]

    Box(Modifier.fillMaxWidth().heightIn(min = 120.dp)) {
        Column(Modifier.fillMaxWidth()) {
            Text("${vm.greeting}，${vm.realName.ifBlank { AppState.displayName }}",
                fontSize = 24.sp, fontWeight = FontWeight.SemiBold, color = Ink,
                letterSpacing = (-0.3).sp)
            Spacer(Modifier.height(Dimens.space4))
            Row(verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(Dimens.space3)) {
                MetaPill(dateText)
                if (vm.department.isNotBlank()) MetaPill(vm.department)
                if (vm.roleName.isNotBlank()) MetaPill(vm.roleName)
                if (AppState.agentName.isNotBlank()) MetaPill(AppState.agentName)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.size(6.dp).clip(CircleShape)
                        .background(if (vm.aiOnline) Ok else Muted))
                    Spacer(Modifier.width(Dimens.space2))
                    Text(if (vm.aiOnline) "AI 助手在线" else "AI 助手离线 · 基础功能正常",
                        fontSize = 12.sp, color = Muted)
                }
            }
        }
    }
}

/** 浅底方案：白底 + 标准描边 + 次级文字（原为深底半透明白，随欢迎条去背景一并调整） */
@Composable
private fun MetaPill(text: String) {
    val shape = RoundedCornerShape(Dimens.radiusPill)
    Box(
        Modifier.clip(shape)
            .background(SurfaceColor)
            .border(1.dp, Line, shape)
            .padding(horizontal = 11.dp, vertical = 5.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(text, fontSize = 12.sp, color = Ink2, fontWeight = FontWeight.Medium)
    }
}

// ---------------- 2×2 四大功能卡 ----------------

@Composable
private fun FeatureGrid() {
    val items = AppNav.coreItems
    Column(verticalArrangement = Arrangement.spacedBy(Dimens.space4)) {
        items.chunked(2).forEach { row ->
            Row(horizontalArrangement = Arrangement.spacedBy(Dimens.space4)) {
                row.forEach { item -> FeatureCard(item, Modifier.weight(1f)) }
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
    val elevation by animateDpAsState(if (hovered) Dimens.elevFloat else Dimens.elevRaised)
    val arrow by animateDpAsState(if (hovered) 6.dp else 0.dp)

    Surface(
        modifier = modifier.height(HOME_FEATURE_CARD_HEIGHT).offset(y = lift),
        shape = RoundedCornerShape(Dimens.radiusSheet),
        elevation = elevation,
        color = Color.Transparent,
    ) {
        Box(
            Modifier.fillMaxSize()
                .background(Brush.linearGradient(listOf(palette.start, palette.end)))
                .clickable(interactionSource = interaction, indication = null) {
                    AppState.navigate(item.screen, item.adminTab)
                }
                .padding(Dimens.space5),
        ) {
            Box(
                Modifier.size(132.dp).align(Alignment.TopEnd)
                    .offset(x = 44.dp, y = (-52).dp)
                    .clip(CircleShape).background(Color.White.copy(alpha = 0.10f)),
            )
            Icon(
                item.icon, contentDescription = null,
                tint = Color.White.copy(alpha = 0.13f),
                modifier = Modifier.size(Dimens.iconDeco).align(Alignment.BottomEnd)
                    .offset(x = 12.dp, y = 20.dp),
            )

            Column(Modifier.fillMaxSize()) {
                Box(
                    Modifier.size(Dimens.iconFeature).clip(RoundedCornerShape(Dimens.radiusLg))
                        .background(Color.White.copy(alpha = 0.18f))
                        .border(1.dp, Color.White.copy(alpha = 0.22f),
                            RoundedCornerShape(Dimens.radiusLg)),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(item.icon, contentDescription = null, tint = Color.White,
                        modifier = Modifier.size(Dimens.iconLg))
                }
                Spacer(Modifier.weight(1f))
                Text(item.label, fontSize = 20.sp, fontWeight = FontWeight.SemiBold,
                    color = Color.White, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Spacer(Modifier.height(Dimens.space1 + 2.dp))
                Text(item.desc, fontSize = 12.5.sp, color = Color.White.copy(alpha = 0.86f),
                    maxLines = 1, overflow = TextOverflow.Ellipsis)
                Spacer(Modifier.height(Dimens.space3))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(
                        Modifier.clip(RoundedCornerShape(Dimens.radiusPill))
                            .background(Color.White.copy(alpha = 0.16f))
                            .padding(horizontal = 10.dp, vertical = 4.dp),
                    ) {
                        Text("开始使用", fontSize = 12.sp, color = Color.White,
                            fontWeight = FontWeight.Medium)
                    }
                    Spacer(Modifier.width(Dimens.space2))
                    Text("→", fontSize = 14.sp, color = Color.White,
                        modifier = Modifier.offset(x = arrow))
                }
            }
        }
    }
}

/** 首页 2×2 卡片高度：收窄后仍保证「图标 + 标题 + 说明 + 开始使用」四层完整可读 */
private val HOME_FEATURE_CARD_HEIGHT = 160.dp

/** 首页四卡对应功能色（供其他页面复用） */
fun softColorOf(screen: AppScreen): Color = when (screen) {
    AppScreen.WRITING -> FeatureWriteSoft
    AppScreen.TEMPLATES -> FeatureTemplateSoft
    AppScreen.PPT -> FeaturePptSoft
    AppScreen.FORMAT_CHECK -> FeatureCheckSoft
    else -> AppBg
}
