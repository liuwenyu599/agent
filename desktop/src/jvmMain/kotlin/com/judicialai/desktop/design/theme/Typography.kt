package com.judicialai.desktop.design.theme

import androidx.compose.material.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

/**
 * 字号层级（v4.0）
 * display / title / section / body / label，桌面上字号阶梯更清晰，
 * 避免「标题和正文差不多大」的后台观感。
 */
val AppTypography = Typography(
    h1 = TextStyle(fontSize = 30.sp, fontWeight = FontWeight.Bold, lineHeight = 40.sp),
    h2 = TextStyle(fontSize = 24.sp, fontWeight = FontWeight.SemiBold, lineHeight = 32.sp),
    h3 = TextStyle(fontSize = 19.sp, fontWeight = FontWeight.SemiBold, lineHeight = 27.sp),
    h4 = TextStyle(fontSize = 16.sp, fontWeight = FontWeight.SemiBold, lineHeight = 24.sp),
    h5 = TextStyle(fontSize = 20.sp, fontWeight = FontWeight.Bold),
    h6 = TextStyle(fontSize = 15.sp, fontWeight = FontWeight.SemiBold, lineHeight = 22.sp),
    subtitle1 = TextStyle(fontSize = 15.sp, fontWeight = FontWeight.Medium, lineHeight = 22.sp),
    subtitle2 = TextStyle(fontSize = 13.5.sp, fontWeight = FontWeight.Medium, lineHeight = 20.sp),
    body1 = TextStyle(fontSize = 14.sp, lineHeight = 22.sp),
    body2 = TextStyle(fontSize = 13.sp, lineHeight = 20.sp),
    caption = TextStyle(fontSize = 12.sp, lineHeight = 18.sp),
    overline = TextStyle(fontSize = 11.sp, fontWeight = FontWeight.Medium, lineHeight = 16.sp),
    button = TextStyle(fontSize = 13.5.sp, fontWeight = FontWeight.Medium),
)
