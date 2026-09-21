package com.judicialai.desktop.design.components

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.Button
import androidx.compose.material.ButtonDefaults
import androidx.compose.material.Icon
import androidx.compose.material.IconButton
import androidx.compose.material.OutlinedButton
import androidx.compose.material.Text
import androidx.compose.material.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.design.theme.Dimens
import com.judicialai.desktop.design.theme.Muted
import com.judicialai.desktop.design.theme.OnPrimaryText
import com.judicialai.desktop.design.theme.Primary

/** 按钮层级：一屏内只允许一个 PRIMARY，避免操作权重失衡 */
enum class AppButtonKind { PRIMARY, SECONDARY, TEXT, DANGER }

@Composable
fun AppButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    kind: AppButtonKind = AppButtonKind.PRIMARY,
    icon: ImageVector? = null,
    tint: Color = Primary,
) {
    val shape = RoundedCornerShape(Dimens.radiusSm)
    val textColor = when (kind) {
        AppButtonKind.PRIMARY -> OnPrimaryText
        AppButtonKind.DANGER -> OnPrimaryText
        else -> tint
    }
    val content: @Composable androidx.compose.foundation.layout.RowScope.() -> Unit = {
        if (icon != null) {
            Icon(icon, contentDescription = null, tint = textColor,
                modifier = Modifier.size(Dimens.iconSm))
            Spacer(Modifier.width(Dimens.space2))
        }
        Text(text, fontSize = 13.sp, color = textColor)
    }
    when (kind) {
        AppButtonKind.PRIMARY -> Button(
            onClick = onClick, enabled = enabled, modifier = modifier, shape = shape,
            contentPadding = PaddingValues(horizontal = 16.dp, vertical = 9.dp),
            colors = ButtonDefaults.buttonColors(backgroundColor = tint),
            content = content,
        )
        AppButtonKind.DANGER -> Button(
            onClick = onClick, enabled = enabled, modifier = modifier, shape = shape,
            contentPadding = PaddingValues(horizontal = 16.dp, vertical = 9.dp),
            colors = ButtonDefaults.buttonColors(backgroundColor = tint),
            content = content,
        )
        AppButtonKind.SECONDARY -> OutlinedButton(
            onClick = onClick, enabled = enabled, modifier = modifier, shape = shape,
            contentPadding = PaddingValues(horizontal = 16.dp, vertical = 9.dp),
            content = content,
        )
        AppButtonKind.TEXT -> TextButton(
            onClick = onClick, enabled = enabled, modifier = modifier, shape = shape,
            content = content,
        )
    }
}

@Composable
fun AppIconButton(
    icon: ImageVector,
    contentDescription: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    tint: Color = Muted,
) {
    IconButton(onClick = onClick, modifier = modifier.size(36.dp)) {
        Icon(icon, contentDescription = contentDescription, tint = tint,
            modifier = Modifier.size(Dimens.iconMd))
    }
}
