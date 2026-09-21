package com.judicialai.desktop.design.theme

import androidx.compose.material.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

val AppTypography = Typography(
    h1 = TextStyle(fontSize = 28.sp, fontWeight = FontWeight.Bold, lineHeight = 38.sp),
    h2 = TextStyle(fontSize = 22.sp, fontWeight = FontWeight.SemiBold, lineHeight = 30.sp),
    h3 = TextStyle(fontSize = 18.sp, fontWeight = FontWeight.SemiBold, lineHeight = 26.sp),
    h4 = TextStyle(fontSize = 16.sp, fontWeight = FontWeight.SemiBold, lineHeight = 24.sp),
    h5 = TextStyle(fontSize = 20.sp, fontWeight = FontWeight.Bold),
    h6 = TextStyle(fontSize = 17.sp, fontWeight = FontWeight.SemiBold),
    subtitle1 = TextStyle(fontSize = 15.sp, fontWeight = FontWeight.Medium),
    subtitle2 = TextStyle(fontSize = 13.sp, fontWeight = FontWeight.Medium),
    body1 = TextStyle(fontSize = 14.sp, lineHeight = 22.sp),
    body2 = TextStyle(fontSize = 13.sp, lineHeight = 20.sp),
    caption = TextStyle(fontSize = 12.sp, lineHeight = 18.sp),
    button = TextStyle(fontSize = 14.sp, fontWeight = FontWeight.Medium),
)

