package com.judicialai.desktop.design.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsHoveredAsState
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.MaterialTheme
import androidx.compose.material.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.judicialai.desktop.design.theme.Dimens
import com.judicialai.desktop.design.theme.Line
import com.judicialai.desktop.design.theme.LineStrong
import com.judicialai.desktop.design.theme.LineSubtle
import com.judicialai.desktop.design.theme.Surface as SurfaceColor
import com.judicialai.desktop.design.theme.SurfaceDeep
import com.judicialai.desktop.design.theme.SurfaceTonal

/**
 * 卡片 / 面板层级（v4.0）
 *
 * 三个层级，避免所有区域都是「白底 + 1px 灰边 + 12dp 圆角」：
 * - [AppCardRaised]：白色 + 极浅描边 + 微弱投影，主内容容器；
 * - [AppCardTonal]：tonal 底 + 无描边，二级分区 / 内嵌块；
 * - [AppCardOutline]：透明底 + 描边，弱化容器 / 分组框。
 */

@Composable
fun AppCardRaised(
    modifier: Modifier = Modifier,
    onClick: (() -> Unit)? = null,
    padding: Dp = Dimens.space5,
    content: @Composable ColumnScope.() -> Unit,
) {
    val shape = RoundedCornerShape(Dimens.radiusLg)
    val interaction = remember { MutableInteractionSource() }
    val hovered by interaction.collectIsHoveredAsState()
    Surface(
        modifier = modifier.fillMaxWidth()
            .then(
                if (onClick != null) Modifier.clickable(
                    interactionSource = interaction, indication = null
                ) { onClick() } else Modifier
            ),
        shape = shape,
        color = SurfaceColor,
        elevation = if (hovered && onClick != null) Dimens.elevRaised else Dimens.elevCard,
    ) {
        Column(
            Modifier.fillMaxWidth()
                .border(
                    1.dp,
                    if (hovered && onClick != null) LineStrong else LineSubtle,
                    shape,
                )
                .padding(padding),
            content = content,
        )
    }
}

@Composable
fun AppCardTonal(
    modifier: Modifier = Modifier,
    onClick: (() -> Unit)? = null,
    tint: Color = SurfaceTonal,
    padding: Dp = Dimens.space4,
    content: @Composable ColumnScope.() -> Unit,
) {
    val shape = RoundedCornerShape(Dimens.radiusLg)
    val interaction = remember { MutableInteractionSource() }
    val hovered by interaction.collectIsHoveredAsState()
    val bg = if (hovered && onClick != null) SurfaceDeep else tint
    Column(
        modifier.fillMaxWidth()
            .clip(shape)
            .background(bg)
            .then(
                if (onClick != null) Modifier.clickable(
                    interactionSource = interaction, indication = null
                ) { onClick() } else Modifier
            )
            .padding(padding),
        content = content,
    )
}

@Composable
fun AppCardOutline(
    modifier: Modifier = Modifier,
    padding: Dp = Dimens.space4,
    tint: Color = Color.Transparent,
    content: @Composable ColumnScope.() -> Unit,
) {
    val shape = RoundedCornerShape(Dimens.radiusLg)
    Column(
        modifier.fillMaxWidth()
            .clip(shape)
            .background(tint)
            .border(1.dp, Line, shape)
            .padding(padding),
        content = content,
    )
}

/** 文档纸张：智能写作正文区与模板预览使用，与卡片区分质感 */
@Composable
fun DocumentSurface(
    modifier: Modifier = Modifier,
    padding: Dp = Dimens.space8,
    pagePadding: PaddingValues? = null,
    content: @Composable ColumnScope.() -> Unit,
) {
    val shape = RoundedCornerShape(Dimens.radiusMd)
    Surface(
        modifier = modifier.fillMaxWidth(),
        shape = shape,
        color = SurfaceColor,
        elevation = Dimens.elevFloat,
    ) {
        Column(
            Modifier.fillMaxWidth()
                .border(1.dp, LineSubtle, shape)
                .padding(pagePadding ?: PaddingValues(padding)),
            content = content,
        )
    }
}

/**
 * 统一内容卡片：白底 + 描边 + 16dp 圆角（兼容旧调用）
 */
@Composable
fun SurfaceCard(
    modifier: Modifier = Modifier,
    elevation: Dp = Dimens.elevCard,
    onClick: (() -> Unit)? = null,
    content: @Composable ColumnScope.() -> Unit,
) {
    AppCardRaised(modifier = modifier, onClick = onClick, content = content)
}

/** 带内边距的卡片（默认 16dp） */
@Composable
fun AppCard(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    AppCardRaised(modifier = modifier, padding = Dimens.space4, content = content)
}

/** 次级面板：tonal 底，用于弱化区域 */
@Composable
fun SoftPanel(
    modifier: Modifier = Modifier,
    background: Color = MaterialTheme.colors.surface,
    content: @Composable ColumnScope.() -> Unit,
) {
    Column(
        modifier
            .clip(RoundedCornerShape(Dimens.radiusLg))
            .background(background)
            .padding(Dimens.space4),
        content = content,
    )
}

/** 1px 分隔线 */
@Composable
fun Hairline(modifier: Modifier = Modifier) {
    Box(modifier.fillMaxWidth().height(1.dp).background(LineSubtle))
}

/** tonal 渐变分区底：用于页面局部强调，不做满屏渐变 */
@Composable
fun TonalGradientBlock(
    modifier: Modifier = Modifier,
    colors: List<Color>,
    content: @Composable () -> Unit,
) {
    Box(modifier.background(Brush.linearGradient(colors))) { content() }
}
