package com.judicialai.desktop.design.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.Icon
import androidx.compose.material.Surface
import androidx.compose.material.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.judicialai.desktop.design.theme.BrandEnd
import com.judicialai.desktop.design.theme.BrandStart
import com.judicialai.desktop.design.theme.Dimens
import com.judicialai.desktop.design.theme.Ink
import com.judicialai.desktop.design.theme.Ink2
import com.judicialai.desktop.design.theme.Line
import com.judicialai.desktop.design.theme.OnPrimaryText
import com.judicialai.desktop.design.theme.Surface as SurfaceColor
import com.judicialai.desktop.design.theme.SurfaceDeep

/**
 * 统一对话框（v4.0）
 *
 * 头部为品牌渐变条（与 Header 同一套视觉语言），内容区可滚动，
 * 底部操作区固定，避免使用 Material 默认 AlertDialog 的后台观感。
 */
@Composable
fun AppDialog(
    onDismissRequest: () -> Unit,
    title: String,
    modifier: Modifier = Modifier,
    subtitle: String = "",
    icon: ImageVector? = null,
    width: Dp = 560.dp,
    maxHeight: Dp = 680.dp,
    actions: @Composable () -> Unit,
    content: @Composable () -> Unit,
) {
    Dialog(
        onDismissRequest = onDismissRequest,
        properties = DialogProperties(dismissOnBackPress = true, dismissOnClickOutside = false),
    ) {
        Surface(
            modifier = modifier.width(width).heightIn(max = maxHeight),
            shape = RoundedCornerShape(Dimens.radiusSheet),
            color = SurfaceColor,
            elevation = Dimens.elevDialog,
        ) {
            Column(Modifier.fillMaxWidth()) {
                // 品牌头条
                Box(
                    Modifier.fillMaxWidth()
                        .background(Brush.horizontalGradient(listOf(BrandStart, BrandEnd)))
                        .padding(horizontal = Dimens.space6, vertical = Dimens.space4),
                ) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        if (icon != null) {
                            Box(
                                Modifier.size(34.dp)
                                    .clip(RoundedCornerShape(Dimens.radiusSm))
                                    .background(OnPrimaryText.copy(alpha = 0.16f)),
                                contentAlignment = Alignment.Center,
                            ) {
                                Icon(icon, contentDescription = null, tint = OnPrimaryText,
                                    modifier = Modifier.size(Dimens.iconMd))
                            }
                            Spacer(Modifier.width(Dimens.space3))
                        }
                        Column(Modifier.weight(1f)) {
                            Text(title, fontSize = 16.sp, fontWeight = FontWeight.SemiBold,
                                color = OnPrimaryText)
                            if (subtitle.isNotBlank()) {
                                Spacer(Modifier.height(2.dp))
                                Text(subtitle, fontSize = 12.sp,
                                    color = OnPrimaryText.copy(alpha = 0.78f), lineHeight = 18.sp)
                            }
                        }
                    }
                }

                Column(
                    Modifier.weight(1f, fill = false).verticalScroll(rememberScrollState())
                        .padding(Dimens.space5),
                    verticalArrangement = Arrangement.spacedBy(Dimens.space3 - 2.dp),
                ) { content() }

                Box(Modifier.fillMaxWidth().heightLine()) {}
                Row(
                    Modifier.fillMaxWidth().background(SurfaceDeep)
                        .padding(horizontal = Dimens.space6, vertical = Dimens.space4),
                    horizontalArrangement = Arrangement.End,
                    verticalAlignment = Alignment.CenterVertically,
                ) { actions() }
            }
        }
    }
}

private fun Modifier.heightLine(): Modifier =
    this.fillMaxWidth().height(1.dp).background(Line)
