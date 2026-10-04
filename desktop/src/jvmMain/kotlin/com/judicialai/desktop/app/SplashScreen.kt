package com.judicialai.desktop.app

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.design.theme.rememberAppLogo

/**
 * 启动页（类似豆包开屏）：应用 Logo + 名称，主窗口内容初始化期间展示。
 * 深藏青渐变背景，与登录页主色系一致；红色徽标在深色背景上更突出。
 * 由 Main.kt 控制展示时长，到期自动切换到 App()。
 */
@Composable
fun SplashScreen() {
    val transition = rememberInfiniteTransition(label = "splash")
    val dotAlpha by transition.animateFloat(
        initialValue = 0.25f, targetValue = 1f,
        animationSpec = infiniteRepeatable(tween(800), RepeatMode.Reverse),
        label = "dots",
    )
    Box(
        Modifier.fillMaxSize().background(
            // 深藏青渐变：与登录页/顶栏品牌色一致；红色徽标在深色背景上更突出
            Brush.verticalGradient(listOf(Color(0xFF0E1F38), Color(0xFF16263F)))
        ),
        contentAlignment = Alignment.Center,
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Image(
                rememberAppLogo(), contentDescription = "应用 Logo",
                modifier = Modifier.size(112.dp),
                contentScale = ContentScale.Fit,
            )
            Spacer(Modifier.height(24.dp))
            Text(
                "白云司法局智慧办公平台",
                color = Color.White, fontSize = 24.sp,
                fontWeight = FontWeight.Bold, letterSpacing = 4.sp,
            )
            Spacer(Modifier.height(10.dp))
            Text(
                "公文写作 · 格式校验 · PPT 助手 · 知识库",
                color = Color.White.copy(alpha = 0.75f), fontSize = 13.sp,
                letterSpacing = 2.sp,
            )
            Spacer(Modifier.height(36.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                repeat(3) {
                    Box(Modifier.size(7.dp).background(
                        Color.White.copy(alpha = dotAlpha), CircleShape))
                }
            }
        }
    }
}
