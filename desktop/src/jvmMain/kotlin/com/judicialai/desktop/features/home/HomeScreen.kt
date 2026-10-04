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
import androidx.compose.material.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Stroke
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.app.AppNav
import com.judicialai.desktop.app.AppScreen
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.app.NavItem
import com.judicialai.desktop.design.components.paletteOf
import com.judicialai.desktop.design.theme.AppBg
import com.judicialai.desktop.design.theme.Dimens
import com.judicialai.desktop.design.theme.FeatureCheckEnd
import com.judicialai.desktop.design.theme.FeatureCheckSoft
import com.judicialai.desktop.design.theme.FeaturePptEnd
import com.judicialai.desktop.design.theme.FeaturePptSoft
import com.judicialai.desktop.design.theme.FeatureTemplateEnd
import com.judicialai.desktop.design.theme.FeatureTemplateSoft
import com.judicialai.desktop.design.theme.FeatureWriteEnd
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
 * 工作台（HOME · v4.1）
 *
 * 结构 = 欢迎条（无背景，页面底色 + 科室上下文） + 2×2 彩色功能卡。
 * 四大功能卡仍是唯一的视觉中心，位置与顺序不变；
 * 本版只做视觉升级：对角深浅渐变 + 同色投影 + 玻璃图标座 + 光环/光带装饰，
 * 页面四角加极淡的功能色回声光晕，欢迎条下加四色渐变点缀条。
 */
@Composable
fun HomeScreen(vm: HomeViewModel = remember { HomeViewModel() }) {
    Box(Modifier.fillMaxSize().background(AppBg).echoGlow()) {
        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState())
                .padding(horizontal = Dimens.space8, vertical = Dimens.space5),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            // 首页 2×2 收窄：局部宽度，不动 Dimens.homeMaxWidth 全局 token
            Box(Modifier.widthIn(max = HOME_CONTENT_MAX_WIDTH)) {
                Column(verticalArrangement = Arrangement.spacedBy(Dimens.space6)) {
                    WelcomeBand(vm)
                    FeatureGrid()
                }
            }
        }
    }
}

/** 首页内容最大宽：比全局 homeMaxWidth 更窄，让 2×2 格子更紧凑 */
private val HOME_CONTENT_MAX_WIDTH = 1000.dp

/** 页面四角的极淡功能色回声光晕（drawBehind 绘制，不参与测量布局） */
private fun Modifier.echoGlow(): Modifier = drawBehind {
    val radius = size.width * 0.42f
    fun glow(cx: Float, cy: Float, color: Color) {
        drawCircle(
            brush = Brush.radialGradient(
                colors = listOf(color.copy(alpha = 0.08f), Color.Transparent),
                center = Offset(cx, cy), radius = radius,
            ),
            radius = radius, center = Offset(cx, cy),
        )
    }
    glow(size.width * 0.02f, size.height * 0.02f, FeatureWriteEnd)
    glow(size.width * 0.98f, size.height * 0.05f, FeatureTemplateEnd)
    glow(size.width * 0.03f, size.height * 0.98f, FeaturePptEnd)
    glow(size.width * 0.97f, size.height * 0.96f, FeatureCheckEnd)
}

// ---------------- 欢迎条（无背景，页面底色） ----------------

@Composable
private fun WelcomeBand(vm: HomeViewModel) {
    val today = LocalDate.now()
    val dateText = today.format(DateTimeFormatter.ofPattern("yyyy年M月d日")) +
        "  " + WEEKDAYS[(today.dayOfWeek.value + 6) % 7]

    Box(Modifier.fillMaxWidth().heightIn(min = 120.dp)) {
        Column(Modifier.fillMaxWidth()) {
            Text("${vm.greeting}，${vm.realName.ifBlank { AppState.displayName }}",
                fontSize = 26.sp, fontWeight = FontWeight.Bold, color = Ink,
                letterSpacing = (-0.5).sp)
            // 四功能色渐变点缀条：与 2×2 卡片同一色彩语言
            Spacer(Modifier.height(Dimens.space3))
            Box(
                Modifier.size(width = 64.dp, height = 4.dp)
                    .clip(RoundedCornerShape(Dimens.radiusPill))
                    .background(Brush.linearGradient(listOf(
                        FeatureWriteEnd, FeatureTemplateEnd, FeaturePptEnd, FeatureCheckEnd,
                    ))),
            )
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
                    Text(if (vm.aiOnline) "AI 助手在线" else "AI 服务离线 · 智能生成功能暂不可用",
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
    Column(verticalArrangement = Arrangement.spacedBy(Dimens.space5)) {
        items.chunked(2).forEach { row ->
            Row(horizontalArrangement = Arrangement.spacedBy(Dimens.space5)) {
                row.forEach { item -> FeatureCard(item, Modifier.weight(1f)) }
            }
        }
    }
}

@Composable
private fun FeatureCard(item: NavItem, modifier: Modifier = Modifier) {
    val palette = paletteOf(item.screen)
    // 渐变三停：起点明显压暗、终点提亮，形成强光向与纵深（深→亮）
    val gradient = listOf(
        lerp(palette.start, Color.Black, 0.18f),
        palette.end,
        lerp(palette.end, Color.White, 0.14f),
    )
    val interaction = remember { MutableInteractionSource() }
    val hovered by interaction.collectIsHoveredAsState()
    val lift by animateDpAsState(if (hovered) (-4).dp else 0.dp)
    val elevation by animateDpAsState(if (hovered) 12.dp else Dimens.elevRaised)
    val arrow by animateDpAsState(if (hovered) 6.dp else 0.dp)
    val ctaAlpha by androidx.compose.animation.core.animateFloatAsState(
        if (hovered) 0.30f else 0.18f)
    val shape = RoundedCornerShape(Dimens.radiusXl)

    Box(
        modifier = modifier.height(HOME_FEATURE_CARD_HEIGHT).offset(y = lift)
            // 同色投影：阴影带卡片主色，浮起时更明显
            .shadow(elevation, shape, ambientColor = palette.end, spotColor = palette.end)
            .clip(shape)
            .border(1.dp, Color.White.copy(alpha = 0.10f), shape)
            .background(Brush.linearGradient(gradient))
            // 装饰（克制、机构感、不抢内容）：
            // 右上角同心细弧（刻度/印章式）+ 左下角纵深暗角（增强对比）
            .drawBehind {
                val stroke = Stroke(width = 1.dp.toPx(), cap = StrokeCap.Round)
                val cx = size.width
                val cy = 0f
                repeat(4) { i ->
                    val r = (26 + i * 20).dp.toPx()
                    drawArc(
                        color = Color.White.copy(alpha = 0.13f),
                        startAngle = 180f, sweepAngle = 90f, useCenter = false,
                        topLeft = Offset(cx - r, cy - r), size = Size(r * 2, r * 2),
                        style = stroke,
                    )
                }
                drawCircle(
                    brush = Brush.radialGradient(
                        colors = listOf(Color.Transparent, Color.Black.copy(alpha = 0.22f)),
                        center = Offset(0f, size.height), radius = size.width * 0.78f,
                    ),
                    radius = size.width * 0.78f, center = Offset(0f, size.height),
                )
            }
            .clickable(interactionSource = interaction, indication = null) {
                AppState.navigate(item.screen, item.adminTab)
            }
            .padding(Dimens.space5),
    ) {
        // 右上角一枚精细实心小光点：校准视觉重心，刻度感
        Box(
            Modifier.size(7.dp).clip(CircleShape)
                .background(Color.White.copy(alpha = 0.55f))
                .align(Alignment.TopEnd).offset(x = (-10).dp, y = 10.dp),
        )

        // —— 内容层 ——
        Column(Modifier.fillMaxSize()) {
            Box(
                Modifier.size(Dimens.iconFeature).clip(RoundedCornerShape(Dimens.radiusLg))
                    .background(Color.White.copy(alpha = 0.20f))
                    .border(1.dp, Color.White.copy(alpha = 0.28f),
                        RoundedCornerShape(Dimens.radiusLg)),
                contentAlignment = Alignment.Center,
            ) {
                Icon(item.icon, contentDescription = null, tint = Color.White,
                    modifier = Modifier.size(Dimens.iconLg))
            }
            Spacer(Modifier.weight(1f))
            Text(item.label, fontSize = 21.sp, fontWeight = FontWeight.Bold,
                color = Color.White, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Spacer(Modifier.height(Dimens.space1 + 2.dp))
            Text(item.desc, fontSize = 12.5.sp, color = Color.White.copy(alpha = 0.88f),
                maxLines = 1, overflow = TextOverflow.Ellipsis)
            Spacer(Modifier.height(Dimens.space3))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    Modifier.clip(RoundedCornerShape(Dimens.radiusPill))
                        .background(Color.White.copy(alpha = ctaAlpha))
                        .padding(horizontal = 12.dp, vertical = 5.dp),
                ) {
                    Text("开始使用", fontSize = 12.sp, color = Color.White,
                        fontWeight = FontWeight.SemiBold)
                }
                Spacer(Modifier.width(Dimens.space2))
                Text("→", fontSize = 14.sp, color = Color.White,
                    modifier = Modifier.offset(x = arrow))
            }
        }
    }
}

/** 首页 2×2 卡片高度：收窄后仍保证「图标 + 标题 + 说明 + 开始使用」四层完整可读 */
private val HOME_FEATURE_CARD_HEIGHT = 176.dp

/** 首页四卡对应功能色（供其他页面复用） */
fun softColorOf(screen: AppScreen): Color = when (screen) {
    AppScreen.WRITING -> FeatureWriteSoft
    AppScreen.TEMPLATES -> FeatureTemplateSoft
    AppScreen.PPT -> FeaturePptSoft
    AppScreen.FORMAT_CHECK -> FeatureCheckSoft
    else -> AppBg
}
