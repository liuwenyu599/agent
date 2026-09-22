package com.judicialai.desktop.design.components

import androidx.compose.animation.animateContentSize
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsHoveredAsState
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.CircularProgressIndicator
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
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.design.theme.AiIndigo
import com.judicialai.desktop.design.theme.AiSoft
import com.judicialai.desktop.design.theme.AiViolet
import com.judicialai.desktop.design.theme.Danger
import com.judicialai.desktop.design.theme.Dimens
import com.judicialai.desktop.design.theme.Ink
import com.judicialai.desktop.design.theme.Ink2
import com.judicialai.desktop.design.theme.Line
import com.judicialai.desktop.design.theme.LineStrong
import com.judicialai.desktop.design.theme.Muted2
import com.judicialai.desktop.design.theme.OnPrimaryText
import com.judicialai.desktop.design.theme.Primary
import com.judicialai.desktop.design.theme.PrimaryDeep
import com.judicialai.desktop.design.theme.PrimarySoft
import com.judicialai.desktop.design.theme.Surface
import com.judicialai.desktop.design.theme.SurfaceDeep
import com.judicialai.desktop.design.theme.SurfaceTonal

/** 按钮层级：一屏内只允许一个 PRIMARY，避免操作权重失衡 */
enum class AppButtonKind { PRIMARY, AI, SECONDARY, TONAL, TEXT, DANGER }

enum class AppButtonSize { SM, MD, LG }

/**
 * 统一按钮（v4.0）
 *
 * 不再直接使用 Material 默认 Button：hover / pressed / disabled 全部自绘，
 * 主操作使用极克制的品牌渐变，AI 操作使用靛蓝→蓝紫渐变以体现智能能力。
 */
@Composable
fun AppButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    kind: AppButtonKind = AppButtonKind.PRIMARY,
    size: AppButtonSize = AppButtonSize.MD,
    icon: ImageVector? = null,
    loading: Boolean = false,
    fill: Boolean = false,
) {
    val interaction = remember { MutableInteractionSource() }
    val hovered by interaction.collectIsHoveredAsState()
    val pressed by interaction.collectIsPressedAsState()

    val height = when (size) {
        AppButtonSize.SM -> Dimens.hSm
        AppButtonSize.MD -> Dimens.hButton
        AppButtonSize.LG -> Dimens.hButtonLg
    }
    val shape = RoundedCornerShape(Dimens.radiusControl)

    val (backgroundBrush, borderColor, textColor) = buttonStyle(kind, enabled, hovered, pressed)

    Box(
        modifier
            .then(if (fill) Modifier.fillAvailableWidth() else Modifier)
            .height(height)
            .defaultMinSize(minWidth = if (size == AppButtonSize.SM) 56.dp else 76.dp)
            .clip(shape)
            .background(backgroundBrush)
            .then(
                if (borderColor != null) Modifier.border(1.dp, borderColor, shape) else Modifier
            )
            .clickable(interactionSource = interaction, indication = null,
                enabled = enabled && !loading) { onClick() }
            .padding(PaddingValues(horizontal = if (size == AppButtonSize.SM) 12.dp else 16.dp)),
        contentAlignment = Alignment.Center,
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            if (loading) {
                CircularProgressIndicator(
                    modifier = Modifier.size(Dimens.iconSm),
                    color = textColor, strokeWidth = 2.dp,
                )
                Spacer(Modifier.width(Dimens.space2))
            } else if (icon != null) {
                Icon(icon, contentDescription = null, tint = textColor,
                    modifier = Modifier.size(Dimens.iconSm))
                Spacer(Modifier.width(Dimens.space2))
            }
            Text(
                text,
                fontSize = if (size == AppButtonSize.SM) 12.5.sp else 13.5.sp,
                fontWeight = FontWeight.Medium,
                color = textColor,
                maxLines = 1,
            )
        }
    }
}

private fun Modifier.fillAvailableWidth(): Modifier = this.then(Modifier.fillMaxWidth())

@Composable
private fun buttonStyle(
    kind: AppButtonKind, enabled: Boolean, hovered: Boolean, pressed: Boolean,
): Triple<Brush, Color?, Color> {
    if (!enabled) {
        return Triple(Brush.verticalGradient(listOf(SurfaceDeep, SurfaceDeep)), Line, Muted2)
    }
    return when (kind) {
        AppButtonKind.PRIMARY -> {
            val start = if (pressed) PrimaryDeep.darken() else if (hovered) PrimaryDeep else Primary
            val end = if (pressed) Primary.darken() else if (hovered) Primary else PrimaryDeep
            Triple(Brush.horizontalGradient(listOf(start, end)), null, OnPrimaryText)
        }
        AppButtonKind.AI -> {
            val start = if (pressed) AiIndigo.darken() else if (hovered) AiIndigo.darken() else AiIndigo
            val end = if (pressed) AiViolet.darken() else AiViolet
            Triple(Brush.horizontalGradient(listOf(start, end)), null, OnPrimaryText)
        }
        AppButtonKind.DANGER -> Triple(
            Brush.verticalGradient(listOf(Danger, Danger)), null, OnPrimaryText)
        AppButtonKind.SECONDARY -> Triple(
            Brush.verticalGradient(
                listOf(if (hovered || pressed) SurfaceTonal else Surface,
                    if (hovered || pressed) SurfaceTonal else Surface)),
            if (hovered || pressed) LineStrong else Line,
            if (hovered || pressed) Primary else Ink2,
        )
        AppButtonKind.TONAL -> Triple(
            Brush.verticalGradient(listOf(PrimarySoft, PrimarySoft)),
            if (hovered || pressed) LineStrong else null,
            Primary,
        )
        AppButtonKind.TEXT -> Triple(
            Brush.verticalGradient(
                listOf(if (hovered || pressed) AiSoft else Color.Transparent,
                    if (hovered || pressed) AiSoft else Color.Transparent)),
            null, Primary,
        )
    }
}

private fun Color.darken(factor: Float = 0.88f): Color = copy(
    red = red * factor, green = green * factor, blue = blue * factor
)

/** 图标按钮：hover 有 tonal 底，桌面端必须有明确反馈 */
@Composable
fun AppIconButton(
    icon: ImageVector,
    contentDescription: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    tint: Color = Ink2,
    size: androidx.compose.ui.unit.Dp = 36.dp,
    active: Boolean = false,
) {
    val interaction = remember { MutableInteractionSource() }
    val hovered by interaction.collectIsHoveredAsState()
    val shape = RoundedCornerShape(Dimens.radiusSm)
    Box(
        modifier.size(size).clip(shape)
            .background(
                when {
                    active -> PrimarySoft
                    hovered -> SurfaceDeep
                    else -> Color.Transparent
                }
            )
            .clickable(interactionSource = interaction, indication = null) { onClick() },
        contentAlignment = Alignment.Center,
    ) {
        Icon(icon, contentDescription = contentDescription,
            tint = if (active) Primary else tint,
            modifier = Modifier.size(Dimens.iconMd))
    }
}

/** 文本链按钮 */
@Composable
fun AppLinkButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    color: Color = Primary,
    icon: ImageVector? = null,
) {
    val interaction = remember { MutableInteractionSource() }
    val hovered by interaction.collectIsHoveredAsState()
    Row(
        modifier.clip(RoundedCornerShape(Dimens.radiusSm))
            .background(if (hovered && enabled) AiSoft else Color.Transparent)
            .clickable(interactionSource = interaction, indication = null, enabled = enabled) {
                onClick()
            }
            .padding(horizontal = 8.dp, vertical = 5.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(text, fontSize = 12.5.sp, fontWeight = FontWeight.Medium,
            color = if (enabled) color else Muted2)
        if (icon != null) {
            Spacer(Modifier.width(Dimens.space1))
            Icon(icon, contentDescription = null, tint = if (enabled) color else Muted2,
                modifier = Modifier.size(Dimens.iconXs))
        }
    }
}
