package com.judicialai.desktop.design.components

import androidx.compose.foundation.background
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
import com.judicialai.desktop.design.theme.Dimens
import com.judicialai.desktop.design.theme.Ink
import com.judicialai.desktop.design.theme.Ink2
import com.judicialai.desktop.design.theme.Muted
import com.judicialai.desktop.design.theme.Primary

/** 业务页统一页头：标题 + 说明 + 右侧操作区 */
@Composable
fun PageHeader(
    title: String,
    subtitle: String = "",
    modifier: Modifier = Modifier,
    actions: @Composable (() -> Unit)? = null,
) {
    Row(
        modifier.fillMaxWidth().padding(bottom = Dimens.space4),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(title, fontSize = 20.sp, fontWeight = FontWeight.SemiBold, color = Ink)
            if (subtitle.isNotBlank()) {
                Spacer(Modifier.height(Dimens.space1))
                Text(subtitle, fontSize = 12.5.sp, color = Ink2)
            }
        }
        if (actions != null) {
            Spacer(Modifier.width(Dimens.space3))
            actions()
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
) {
    Row(modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text(title, fontSize = 13.5.sp, fontWeight = FontWeight.SemiBold, color = Ink,
            modifier = Modifier.weight(1f))
        if (more != null) {
            Text(more, fontSize = 12.sp, color = Primary,
                modifier = Modifier.clip(RoundedCornerShape(Dimens.radiusSm))
                    .clickable(enabled = onMore != null) { onMore?.invoke() }
                    .padding(horizontal = 6.dp, vertical = 3.dp))
        }
    }
}

/** 空状态：图标 + 主文案 + 可选说明 */
@Composable
fun EmptyState(
    text: String,
    modifier: Modifier = Modifier,
    hint: String = "",
    icon: ImageVector? = null,
) {
    Column(
        modifier.fillMaxWidth().padding(vertical = Dimens.space10),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(Dimens.space2),
    ) {
        if (icon != null) {
            Icon(icon, contentDescription = null, tint = Muted,
                modifier = Modifier.size(Dimens.space8))
        }
        Text(text, fontSize = 13.sp, color = Muted)
        if (hint.isNotBlank()) Text(hint, fontSize = 12.sp, color = Muted)
    }
}

/** 加载态（区块级，非全屏） */
@Composable
fun LoadingBlock(text: String = "加载中…", modifier: Modifier = Modifier) {
    Box(modifier.fillMaxWidth().padding(vertical = Dimens.space8),
        contentAlignment = Alignment.Center) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
            Spacer(Modifier.width(Dimens.space2))
            Text(text, fontSize = 12.5.sp, color = Muted)
        }
    }
}

/** 填充父容器的居中加载态 */
@Composable
fun LoadingScreen(text: String = "加载中…") {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(Dimens.space3)) {
            CircularProgressIndicator(Modifier.size(28.dp), strokeWidth = 2.dp)
            Text(text, fontSize = 13.sp, color = Muted)
        }
    }
}

/** 提示条：轻量背景 + 语义色文字 */
@Composable
fun NoticeBar(text: String, fg: Color, bg: Color, modifier: Modifier = Modifier) {
    Box(
        modifier.fillMaxWidth().clip(RoundedCornerShape(Dimens.radiusSm)).background(bg)
            .padding(horizontal = Dimens.space3, vertical = Dimens.space2),
    ) { Text(text, fontSize = 12.5.sp, color = fg) }
}
