package com.judicialai.desktop.design.theme

import androidx.compose.material.MaterialTheme
import androidx.compose.material.lightColors
import androidx.compose.runtime.Composable

private val AppColors = lightColors(
    primary = Primary,
    primaryVariant = PrimaryVariant,
    secondary = Secondary,
    background = Background,
    surface = Surface,
    error = ErrorColor,
    onPrimary = OnPrimaryText,
    onBackground = BodyText,
    onSurface = BodyText,
    onError = OnPrimaryText,
)

@Composable
fun AppTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colors = AppColors,
        typography = AppTypography,
        shapes = AppShapes,
        content = content,
    )
}

