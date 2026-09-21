package com.judicialai.desktop.design.components

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.Icon
import androidx.compose.material.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.design.theme.Dimens
import com.judicialai.desktop.design.theme.Ink
import com.judicialai.desktop.design.theme.Ink2
import com.judicialai.desktop.design.theme.Muted

/** 筛选 / 分类标签；选中态用实心主色，未选中用浅描边 */
@Composable
fun AppChip(
    text: String,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    tint: Color = Ink,
) {
    val bg = if (selected) tint else Color.Transparent
    val fg = if (selected) Color.White else Ink2
    Box(
        modifier.clip(RoundedCornerShape(Dimens.radiusPill))
            .background(bg)
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 6.dp),
    ) { Text(text, fontSize = 12.5.sp, color = fg) }
}

/** 状态标签：错误 / 警告 / 正常 / 中性，颜色由调用方按语义色传入 */
@Composable
fun StatusChip(text: String, fg: Color, bg: Color, modifier: Modifier = Modifier) {
    Box(
        modifier.clip(RoundedCornerShape(Dimens.radiusSm))
            .background(bg)
            .padding(horizontal = 8.dp, vertical = 3.dp),
    ) { Text(text, fontSize = 11.5.sp, color = fg) }
}

/** 带小圆点的元信息行（如 AI 在线状态） */
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
