package com.judicialai.desktop.design.components

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.Card
import androidx.compose.material.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.judicialai.desktop.design.theme.Dimens
import com.judicialai.desktop.design.theme.Line
import com.judicialai.desktop.design.theme.Surface

/**
 * 统一内容卡片：白底 + 1dp 描边 + 12dp 圆角，无重投影。
 * 分区容器优先用 [SurfaceCard]，避免每个页面自己写 Card。
 */
@Composable
fun SurfaceCard(
    modifier: Modifier = Modifier,
    elevation: androidx.compose.ui.unit.Dp = Dimens.elevCard,
    onClick: (() -> Unit)? = null,
    content: @Composable ColumnScope.() -> Unit,
) {
    val shape = RoundedCornerShape(Dimens.radiusMd)
    val base = modifier.clip(shape).background(Surface)
    Card(
        modifier = (if (onClick != null) base.clickable(onClick = onClick) else base).fillMaxWidth(),
        shape = shape,
        elevation = elevation,
        backgroundColor = Surface,
    ) { Column(Modifier.fillMaxWidth(), content = content) }
}

/** 带内边距的卡片（默认 16dp） */
@Composable
fun AppCard(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    Card(modifier.fillMaxWidth(), elevation = Dimens.elevCard,
        shape = RoundedCornerShape(Dimens.radiusMd)) {
        Column(Modifier.padding(Dimens.space4), content = content)
    }
}

/** 次级面板：浅底 + 描边，用于弱化区域（如首页二级区、侧栏分区） */
@Composable
fun SoftPanel(
    modifier: Modifier = Modifier,
    background: Color = MaterialTheme.colors.surface,
    content: @Composable ColumnScope.() -> Unit,
) {
    Column(
        modifier
            .clip(RoundedCornerShape(Dimens.radiusMd))
            .background(background)
            .padding(Dimens.space4),
        content = content,
    )
}

/** 1px 分隔线 */
@Composable
fun Hairline(modifier: Modifier = Modifier) {
    Box(modifier.fillMaxWidth().height(1.dp).background(Line))
}
