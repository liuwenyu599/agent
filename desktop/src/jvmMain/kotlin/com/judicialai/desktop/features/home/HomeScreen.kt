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
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.app.AppNav
import com.judicialai.desktop.app.AppScreen
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.app.NavItem
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

/** 衬线字体：庄重、机构感（与参考设计一致） */
private val SERIF = FontFamily.Serif

/** 首页主区底色：中性浅灰（去掉偏暖米白） */
private val HOME_BG = Color(0xFFE9EBEE)

/** 姓名强调金（参考设计里的低饱和金） */
private val NAME_GOLD = Color(0xFF8C6F3F)

/**
 * 四大功能卡底色（低饱和深色调，庄重不刺眼，参考设计配色）：
 * 写作=黛蓝（深夜蓝，略浅）、模板=墨绿、PPT=紫檀、校验=赭金。
 */
private val MODULE_BG = mapOf(
    AppScreen.WRITING to Color(0xFF234B86),
    AppScreen.TEMPLATES to Color(0xFF1D4A38),
    AppScreen.PPT to Color(0xFF46295E),
    AppScreen.FORMAT_CHECK to Color(0xFF6B4423),
)

/** 卡片 hover 底部描边金 */
private val ACCENT_GOLD = Color(0xFFC29A4A)

/** 四大功能卡英文 eyebrow（参考设计） */
private val MODULE_EN = mapOf(
    AppScreen.WRITING to "AI WRITING",
    AppScreen.TEMPLATES to "TEMPLATES",
    AppScreen.PPT to "SLIDES",
    AppScreen.FORMAT_CHECK to "COMPLIANCE",
)

private val WEEKDAYS = arrayOf("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")

/**
 * 工作台（HOME · v4.3，参考设计风格）
 *
 * 结构 = 欢迎条（中性浅灰底 + 衬线标题）+ 2×2 低饱和深色功能卡。
 * 四卡位置与顺序不变；卡片改为「序号 + 英文 eyebrow + 标题 + 说明 + 箭头」的
 * 庄重排版，去掉花哨装饰；hover 上浮 + 底部金色描边。
 */
@Composable
fun HomeScreen(vm: HomeViewModel = remember { HomeViewModel() }) {
    Box(Modifier.fillMaxSize().background(HOME_BG)) {
        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState())
                .padding(horizontal = Dimens.space8, vertical = Dimens.space6),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Box(Modifier.widthIn(max = HOME_CONTENT_MAX_WIDTH)) {
                Column(
                    verticalArrangement = Arrangement.spacedBy(Dimens.space6),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    WelcomeBand(vm)
                    FeatureGrid()
                }
            }
        }
    }
}

/** 首页内容最大宽：紧凑 2×2 */
private val HOME_CONTENT_MAX_WIDTH = 960.dp

@Composable
private fun WelcomeBand(vm: HomeViewModel) {
    val today = LocalDate.now()
    val dateText = today.format(DateTimeFormatter.ofPattern("yyyy年M月d日")) +
        "  " + WEEKDAYS[(today.dayOfWeek.value + 6) % 7]

    Column(
        Modifier.fillMaxWidth(),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        // 问候语 + 姓名（姓名用低饱和金，呼应机构色，参考设计）
        Row(verticalAlignment = Alignment.Bottom) {
            Text(vm.greeting + "，", fontSize = 34.sp, fontWeight = FontWeight.Bold,
                color = Ink, fontFamily = SERIF, letterSpacing = 1.sp)
            Text(vm.realName.ifBlank { AppState.displayName }, fontSize = 34.sp,
                fontWeight = FontWeight.Bold, color = NAME_GOLD, fontFamily = SERIF,
                letterSpacing = 1.sp)
        }
        Spacer(Modifier.height(Dimens.space3))
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(Dimens.space3),
        ) {
            MetaPill(dateText)
            if (vm.department.isNotBlank()) MetaPill(vm.department)
            if (vm.roleName.isNotBlank()) MetaPill(vm.roleName)
            if (AppState.agentName.isNotBlank()) MetaPill(AppState.agentName)
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(6.dp).clip(CircleShape)
                    .background(if (vm.aiOnline) Ok else Muted))
                Spacer(Modifier.width(Dimens.space2))
                Text(
                    if (vm.aiOnline) "AI 助手在线" else "AI 服务离线 · 智能生成功能暂不可用",
                    fontSize = 12.sp, color = Muted,
                )
            }
        }
    }
}

/** 浅底方案：白底 + 标准描边 + 次级文字 */
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
    Column(
        verticalArrangement = Arrangement.spacedBy(Dimens.space5),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        items.chunked(2).forEach { row ->
            Row(
                Modifier.align(Alignment.CenterHorizontally),
                horizontalArrangement = Arrangement.spacedBy(Dimens.space5),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                row.forEach { item ->
                    FeatureCard(item, Modifier.width(HOME_FEATURE_CARD_SIZE))
                }
            }
        }
    }
}

@Composable
private fun FeatureCard(item: NavItem, modifier: Modifier = Modifier) {
    val screen = item.screen
    val base = MODULE_BG[screen] ?: Ink
    val en = MODULE_EN[screen] ?: ""
    // 轻微光向：上深下亮，保留一点纵深但不喧宾夺主
    val gradient = listOf(lerp(base, Color.Black, 0.10f), lerp(base, Color.White, 0.06f))
    val no = (AppNav.coreItems.indexOf(item) + 1).toString().padStart(2, '0')

    val interaction = remember { MutableInteractionSource() }
    val hovered by interaction.collectIsHoveredAsState()
    val lift by animateDpAsState(if (hovered) (-4).dp else 0.dp)
    val elevation by animateDpAsState(if (hovered) 10.dp else 3.dp)
    val arrowX by animateDpAsState(if (hovered) 6.dp else 0.dp)
    val shape = RoundedCornerShape(Dimens.radiusLg)

    Box(
        modifier = modifier.height(HOME_FEATURE_CARD_SIZE).offset(y = lift)
            // 同色投影：阴影带卡片主色，浮起时更明显
            .shadow(elevation, shape, ambientColor = Color.Black, spotColor = base)
            .clip(shape)
            .border(1.dp, Color.White.copy(alpha = 0.10f), shape)
            .background(Brush.verticalGradient(gradient))
            .clickable(interactionSource = interaction, indication = null) {
                AppState.navigate(item.screen, item.adminTab)
            }
            .padding(Dimens.space5),
    ) {
        Column(
            Modifier.fillMaxSize(),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            // 顶部：序号 + 英文 eyebrow（居中一行）
            Row(
                horizontalArrangement = Arrangement.spacedBy(Dimens.space3),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(no, fontFamily = SERIF, fontSize = 13.sp, letterSpacing = 2.sp,
                    color = Color.White.copy(alpha = 0.62f))
                Text(en, fontFamily = SERIF, fontSize = 11.sp, letterSpacing = 2.sp,
                    color = Color.White.copy(alpha = 0.5f))
            }
            Spacer(Modifier.weight(1f))
            // 中部：标题 + 说明（居中，字号放大）
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text(item.label, fontFamily = SERIF, fontSize = 30.sp,
                    fontWeight = FontWeight.Bold, color = Color.White,
                    letterSpacing = 3.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Spacer(Modifier.height(Dimens.space2))
                Text(item.desc, fontSize = 13.sp,
                    color = Color.White.copy(alpha = 0.72f),
                    letterSpacing = 1.sp, maxLines = 2, overflow = TextOverflow.Ellipsis,
                    textAlign = TextAlign.Center)
            }
            Spacer(Modifier.weight(1f))
            Text("→", fontSize = 22.sp, color = Color.White.copy(alpha = 0.9f),
                modifier = Modifier.offset(x = arrowX))
        }
        // 底部金色短线：唯一装饰线（居中，hover 提亮）
        val lineAlpha by androidx.compose.animation.core.animateFloatAsState(
            if (hovered) 1f else 0.65f)
        Box(
            Modifier.align(Alignment.BottomCenter)
                .padding(bottom = Dimens.space3)
                .width(48.dp).height(2.dp)
                .background(ACCENT_GOLD.copy(alpha = lineAlpha)),
        )
    }
}

/** 首页 2×2 卡片尺寸：正方形，连续缩小 10% 后留白更舒展（不铺满，四周留白） */
private val HOME_FEATURE_CARD_SIZE = 226.8.dp

/** 首页四卡对应功能色（供其他页面复用） */
fun softColorOf(screen: AppScreen): Color = when (screen) {
    AppScreen.WRITING -> FeatureWriteSoft
    AppScreen.TEMPLATES -> FeatureTemplateSoft
    AppScreen.PPT -> FeaturePptSoft
    AppScreen.FORMAT_CHECK -> FeatureCheckSoft
    else -> HOME_BG
}
