package com.judicialai.desktop.design.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.CircularProgressIndicator
import androidx.compose.material.Icon
import androidx.compose.material.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.design.theme.AppBg
import com.judicialai.desktop.design.theme.Dimens
import com.judicialai.desktop.design.theme.Ink
import com.judicialai.desktop.design.theme.Ink2
import com.judicialai.desktop.design.theme.Line
import com.judicialai.desktop.design.theme.LineSubtle
import com.judicialai.desktop.design.theme.Muted
import com.judicialai.desktop.design.theme.Primary
import com.judicialai.desktop.design.theme.PrimarySoft
import com.judicialai.desktop.design.theme.SurfaceDeep

/**
 * 业务页统一页头（v4.0）：eyebrow（分组）→ 标题 → 说明 → 右侧操作。
 * 用层级替代「一行大字 + 一行小字」的后台样式。
 */
@Composable
fun PageHeader(
    title: String,
    subtitle: String = "",
    modifier: Modifier = Modifier,
    eyebrow: String = "",
    actions: @Composable (() -> Unit)? = null,
) {
    Row(
        modifier.fillMaxWidth().padding(bottom = Dimens.space5),
        verticalAlignment = Alignment.Bottom,
    ) {
        Column(Modifier.weight(1f)) {
            if (eyebrow.isNotBlank()) {
                Eyebrow(eyebrow)
                Spacer(Modifier.height(Dimens.space1))
            }
            Text(title, fontSize = 22.sp, fontWeight = FontWeight.SemiBold, color = Ink,
                letterSpacing = (-0.2).sp)
            if (subtitle.isNotBlank()) {
                Spacer(Modifier.height(Dimens.space1 + 2.dp))
                Text(subtitle, fontSize = 12.5.sp, color = Ink2, lineHeight = 19.sp)
            }
        }
        if (actions != null) {
            Spacer(Modifier.width(Dimens.space4))
            Box(Modifier.padding(bottom = 2.dp)) { actions() }
        }
    }
}

/** 区块小标题（卡片内分区标题，与 PageHeader 区分层级） */
@Composable
fun SectionTitle(
    title: String,
    modifier: Modifier = Modifier,
    more: String? = null,
    onMore: (() -> Unit)? = null,
    icon: ImageVector? = null,
    tint: Color = Primary,
) {
    Row(modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        if (icon != null) {
            Box(
                Modifier.size(22.dp).clip(RoundedCornerShape(Dimens.radiusXs))
                    .background(PrimarySoft),
                contentAlignment = Alignment.Center,
            ) {
                Icon(icon, contentDescription = null, tint = tint,
                    modifier = Modifier.size(Dimens.iconXs))
            }
            Spacer(Modifier.width(Dimens.space2))
        }
        Text(title, fontSize = 13.5.sp, fontWeight = FontWeight.SemiBold, color = Ink,
            modifier = Modifier.weight(1f))
        if (more != null) {
            AppLinkButton(more, onClick = { onMore?.invoke() }, enabled = onMore != null)
        }
    }
}

/**
 * 空状态（v4.0）：图标置于 tonal 圆底，主文案 + 说明 + 可选主操作，
 * 不再是一行灰字。
 */
@Composable
fun EmptyState(
    text: String,
    modifier: Modifier = Modifier,
    hint: String = "",
    icon: ImageVector? = null,
    iconTint: Color = Primary,
    action: (@Composable () -> Unit)? = null,
) {
    Column(
        modifier.fillMaxWidth().padding(vertical = Dimens.space8),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(Dimens.space2),
    ) {
        if (icon != null) {
            Box(
                Modifier.size(56.dp).clip(CircleShape).background(PrimarySoft)
                    .border(1.dp, LineSubtle, CircleShape),
                contentAlignment = Alignment.Center,
            ) {
                Icon(icon, contentDescription = null, tint = iconTint,
                    modifier = Modifier.size(Dimens.iconLg))
            }
            Spacer(Modifier.height(Dimens.space1))
        }
        Text(text, fontSize = 13.5.sp, fontWeight = FontWeight.Medium, color = Ink2)
        if (hint.isNotBlank()) {
            Text(hint, fontSize = 12.sp, color = Muted, lineHeight = 18.sp)
        }
        if (action != null) {
            Spacer(Modifier.height(Dimens.space2))
            action()
        }
    }
}

/** 列表空态（更紧凑，用于卡片内） */
@Composable
fun EmptyLine(text: String, modifier: Modifier = Modifier) {
    Box(
        modifier.fillMaxWidth()
            .clip(RoundedCornerShape(Dimens.radiusMd))
            .background(SurfaceDeep)
            .padding(vertical = Dimens.space5, horizontal = Dimens.space4),
        contentAlignment = Alignment.Center,
    ) { Text(text, fontSize = 12.5.sp, color = Muted) }
}

/** 加载态（区块级，非全屏） */
@Composable
fun LoadingBlock(text: String = "加载中…", modifier: Modifier = Modifier) {
    Box(modifier.fillMaxWidth().padding(vertical = Dimens.space8),
        contentAlignment = Alignment.Center) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp, color = Primary)
            Spacer(Modifier.width(Dimens.space2))
            Text(text, fontSize = 12.5.sp, color = Muted)
        }
    }
}

/** 填充父容器的居中加载态 */
@Composable
fun LoadingScreen(text: String = "加载中…") {
    Box(Modifier.fillMaxSize().background(AppBg), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(Dimens.space3)) {
            CircularProgressIndicator(Modifier.size(28.dp), strokeWidth = 2.dp, color = Primary)
            Text(text, fontSize = 13.sp, color = Muted)
        }
    }
}

/** 提示条：轻量背景 + 语义色文字 */
@Composable
fun NoticeBar(text: String, fg: Color, bg: Color, modifier: Modifier = Modifier) {
    InlineNotice(text = text, container = bg, content = fg, modifier = modifier)
}

/** 页面容器：统一页面留白，桌面大屏不出现无意义空白 */
@Composable
fun PageContainer(
    modifier: Modifier = Modifier,
    maxWidth: androidx.compose.ui.unit.Dp = Dimens.contentMaxWidth,
    content: @Composable () -> Unit,
) {
    Box(Modifier.fillMaxSize().background(AppBg), contentAlignment = Alignment.TopCenter) {
        Box(modifier.fillMaxWidth().then(Modifier.widthInMax(maxWidth))) { content() }
    }
}

private fun Modifier.widthInMax(max: androidx.compose.ui.unit.Dp): Modifier =
    this.widthIn(max = max)
