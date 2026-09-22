package com.judicialai.desktop.design.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsHoveredAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.Icon
import androidx.compose.material.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.design.theme.Dimens
import com.judicialai.desktop.design.theme.Ink
import com.judicialai.desktop.design.theme.Ink2
import com.judicialai.desktop.design.theme.Line
import com.judicialai.desktop.design.theme.LineStrong
import com.judicialai.desktop.design.theme.Muted
import com.judicialai.desktop.design.theme.Primary
import com.judicialai.desktop.design.theme.PrimarySoft
import com.judicialai.desktop.design.theme.Surface
import com.judicialai.desktop.design.theme.SurfaceDeep
import com.judicialai.desktop.design.theme.SurfaceTonal

/**
 * 筛选片（v4.0）：未选中为 tonal 底 + 浅描边，选中为品牌 tonal + 描边 + 半粗字。
 * 不再使用「未选中白底 / 选中实心主色」的简陋两态。
 */
@Composable
fun FilterChip(
    text: String,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    count: Int? = null,
    tint: Color = Primary,
) {
    val interaction = remember { MutableInteractionSource() }
    val hovered by interaction.collectIsHoveredAsState()
    val shape = RoundedCornerShape(Dimens.radiusPill)
    val bg = when {
        selected -> PrimarySoft
        hovered -> SurfaceTonal
        else -> Surface
    }
    val border = if (selected) tint.copy(alpha = 0.35f) else if (hovered) LineStrong else Line
    Row(
        modifier.height(Dimens.hSm)
            .clip(shape)
            .background(bg)
            .border(1.dp, border, shape)
            .clickable(interactionSource = interaction, indication = null) { onClick() }
            .padding(horizontal = 13.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text,
            fontSize = 12.5.sp,
            fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
            color = if (selected) tint else Ink2,
        )
        if (count != null) {
            Spacer(Modifier.width(Dimens.space1))
            Box(
                Modifier.clip(RoundedCornerShape(Dimens.radiusPill))
                    .background(if (selected) tint.copy(alpha = 0.14f) else SurfaceDeep)
                    .padding(horizontal = 6.dp, vertical = 1.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text("$count", fontSize = 10.5.sp,
                    color = if (selected) tint else Muted)
            }
        }
    }
}

/** 语义标签：归属、类型等元信息，成对传入前景与底色 */
@Composable
fun TagChip(
    text: String,
    fg: Color,
    bg: Color,
    modifier: Modifier = Modifier,
    icon: ImageVector? = null,
) {
    val shape = RoundedCornerShape(Dimens.radiusXs)
    Row(
        modifier.clip(shape).background(bg).padding(horizontal = 7.dp, vertical = 2.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (icon != null) {
            Icon(icon, contentDescription = null, tint = fg, modifier = Modifier.size(11.dp))
            Spacer(Modifier.width(3.dp))
        }
        Text(text, fontSize = 10.5.sp, fontWeight = FontWeight.Medium, color = fg)
    }
}

/** 状态标签：错误 / 警告 / 正常 / 中性，颜色由调用方按语义色传入 */
@Composable
fun StatusChip(text: String, fg: Color, bg: Color, modifier: Modifier = Modifier) {
    TagChip(text = text, fg = fg, bg = bg, modifier = modifier)
}

/** 带小圆点的元信息行 */
@Composable
fun DotText(text: String, color: Color, modifier: Modifier = Modifier) {
    Row(modifier, verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(6.dp).clip(RoundedCornerShape(Dimens.radiusPill)).background(color))
        Spacer(Modifier.width(Dimens.space2))
        Text(text, fontSize = 12.sp, color = Muted)
    }
}

/** 图标 + 文字的轻量标签 */
@Composable
fun IconLabel(icon: ImageVector, text: String, tint: Color, modifier: Modifier = Modifier) {
    Row(modifier, verticalAlignment = Alignment.CenterVertically) {
        Icon(icon, contentDescription = null, tint = tint, modifier = Modifier.size(14.dp))
        Spacer(Modifier.width(Dimens.space1))
        Text(text, fontSize = 12.sp, color = tint)
    }
}

/** 旧名兼容 */
@Composable
fun AppChip(
    text: String,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    tint: Color = Ink,
) {
    FilterChip(text = text, selected = selected, onClick = onClick, modifier = modifier,
        tint = tint)
}

/**
 * 分段控件（Tab 替代）：比 Material TabRow 更轻量，选中为 tonal 底 + 描边。
 */
@Composable
fun AppSegmentedTabs(
    tabs: List<String>,
    selectedIndex: Int,
    onSelect: (Int) -> Unit,
    modifier: Modifier = Modifier,
) {
    val shape = RoundedCornerShape(Dimens.radiusControl)
    Row(
        modifier.clip(shape).background(SurfaceDeep).padding(4.dp),
        horizontalArrangement = Arrangement.spacedBy(2.dp),
    ) {
        tabs.forEachIndexed { i, t ->
            val active = i == selectedIndex
            val interaction = remember { MutableInteractionSource() }
            val hovered by interaction.collectIsHoveredAsState()
            Box(
                Modifier.weight(1f).height(Dimens.hSm)
                    .clip(shape)
                    .background(if (active) Surface else Color.Transparent)
                    .border(
                        1.dp,
                        if (active) Line else if (hovered) LineStrong else Color.Transparent,
                        shape,
                    )
                    .clickable(interactionSource = interaction, indication = null) { onSelect(i) },
                contentAlignment = Alignment.Center,
            ) {
                Text(t, fontSize = 12.5.sp,
                    fontWeight = if (active) FontWeight.SemiBold else FontWeight.Normal,
                    color = if (active) Primary else Ink2, maxLines = 1)
            }
        }
    }
}
