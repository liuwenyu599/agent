package com.judicialai.desktop.design.components

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.expandVertically
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsHoveredAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.Icon
import androidx.compose.material.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.design.theme.AiIndigo
import com.judicialai.desktop.design.theme.AiInk
import com.judicialai.desktop.design.theme.AiSoft
import com.judicialai.desktop.design.theme.AiSoftStrong
import com.judicialai.desktop.design.theme.Dimens
import com.judicialai.desktop.design.theme.EmeraldInk
import com.judicialai.desktop.design.theme.EmeraldSoft
import com.judicialai.desktop.design.theme.Ink
import com.judicialai.desktop.design.theme.Ink2
import com.judicialai.desktop.design.theme.Line
import com.judicialai.desktop.design.theme.LineSubtle
import com.judicialai.desktop.design.theme.Muted
import com.judicialai.desktop.design.theme.Muted2
import com.judicialai.desktop.design.theme.OnPrimaryText
import com.judicialai.desktop.design.theme.Primary
import com.judicialai.desktop.design.theme.Surface
import com.judicialai.desktop.design.theme.SurfaceDeep
import com.judicialai.desktop.design.theme.SurfaceTonal

/**
 * AI 对话气泡（v4.0）
 * 用户消息为品牌 tonal，AI 消息为浅靛蓝 tonal + 描边，并带 AI 标识，
 * 与普通聊天框区分开。
 */
@Composable
fun AiBubble(
    text: String,
    isUser: Boolean,
    modifier: Modifier = Modifier,
    label: String = "AI",
) {
    val shape = RoundedCornerShape(
        topStart = 12.dp, topEnd = 12.dp,
        bottomStart = if (isUser) 12.dp else 4.dp,
        bottomEnd = if (isUser) 4.dp else 12.dp,
    )
    Column(modifier.fillMaxWidth(), horizontalAlignment = if (isUser) Alignment.End else Alignment.Start) {
        if (!isUser) {
            Row(
                Modifier.padding(bottom = 4.dp, start = 2.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(
                    Modifier.size(16.dp).clip(CircleShape)
                        .background(Brush.linearGradient(listOf(AiIndigo, Primary))),
                    contentAlignment = Alignment.Center,
                ) {
                    Text("A", fontSize = 9.sp, color = OnPrimaryText,
                        fontWeight = FontWeight.Bold)
                }
                Spacer(Modifier.width(6.dp))
                Text(label, fontSize = 11.sp, color = AiInk, fontWeight = FontWeight.Medium)
            }
        }
        Box(
            Modifier.clip(shape)
                .background(if (isUser) Primary else AiSoft)
                .border(
                    1.dp,
                    if (isUser) Primary else AiSoftStrong,
                    shape,
                )
                .padding(horizontal = 12.dp, vertical = 9.dp),
        ) {
            Text(text, fontSize = 12.5.sp, lineHeight = 19.sp,
                color = if (isUser) OnPrimaryText else Ink)
        }
    }
}

/** AI 正在处理：呼吸圆点 + 文案 */
@Composable
fun AiWorkingRow(text: String, modifier: Modifier = Modifier) {
    val shape = RoundedCornerShape(Dimens.radiusPill)
    Row(
        modifier.clip(shape).background(AiSoft).border(1.dp, AiSoftStrong, shape)
            .padding(horizontal = 12.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(6.dp).clip(CircleShape).background(AiIndigo))
        Spacer(Modifier.width(Dimens.space2))
        Text(text, fontSize = 12.sp, color = AiInk, fontWeight = FontWeight.Medium)
    }
}

/** AI 建议操作：tonal 底 + 描边，hover 提亮 */
@Composable
fun AiActionChip(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    icon: ImageVector? = null,
) {
    val interaction = remember { MutableInteractionSource() }
    val hovered by interaction.collectIsHoveredAsState()
    val shape = RoundedCornerShape(Dimens.radiusControl)
    Row(
        modifier.height(Dimens.hSm)
            .clip(shape)
            .background(if (hovered && enabled) AiSoftStrong else AiSoft)
            .border(1.dp, if (hovered && enabled) AiIndigo.copy(alpha = 0.35f) else AiSoftStrong,
                shape)
            .clickable(interactionSource = interaction, indication = null, enabled = enabled) {
                onClick()
            }
            .padding(horizontal = 11.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (icon != null) {
            Icon(icon, contentDescription = null,
                tint = if (enabled) AiIndigo else Muted2,
                modifier = Modifier.size(Dimens.iconXs))
            Spacer(Modifier.width(Dimens.space1))
        }
        Text(text, fontSize = 12.sp, fontWeight = FontWeight.Medium,
            color = if (enabled) AiInk else Muted2, maxLines = 1)
    }
}

/**
 * 上下文资料说明（v4.0）
 * 用「已参考 N 项相关资料」「来自本科室业务知识」表达，
 * 不向普通用户暴露「全局公共知识库 / 本科室知识库」这类实现语言；
 * 用户需要时再展开查看来源。
 */
@Composable
fun ContextSources(
    summary: String,
    sources: List<String>,
    modifier: Modifier = Modifier,
    tint: Color = EmeraldInk,
    container: Color = EmeraldSoft,
    onSourceClick: ((Int) -> Unit)? = null,
) {
    var expanded by remember { mutableStateOf(false) }
    val shape = RoundedCornerShape(Dimens.radiusMd)
    Column(
        modifier.fillMaxWidth().clip(shape).background(container)
            .border(1.dp, LineSubtle, shape),
    ) {
        Row(
            Modifier.fillMaxWidth()
                .clickable { expanded = !expanded }
                .padding(horizontal = 12.dp, vertical = 9.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(Modifier.size(6.dp).clip(CircleShape).background(tint))
            Spacer(Modifier.width(Dimens.space2))
            Text(summary, fontSize = 12.sp, color = tint,
                fontWeight = FontWeight.Medium, modifier = Modifier.weight(1f),
                maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(if (expanded) "收起" else "查看来源", fontSize = 11.5.sp, color = tint)
        }
        AnimatedVisibility(
            visible = expanded && sources.isNotEmpty(),
            enter = expandVertically(),
            exit = shrinkVertically(),
        ) {
            Column(
                Modifier.fillMaxWidth()
                    .background(Surface.copy(alpha = 0.55f))
                    .padding(horizontal = 12.dp, vertical = 8.dp),
                verticalArrangement = Arrangement.spacedBy(5.dp),
            ) {
                sources.forEachIndexed { index, s ->
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Box(
                            Modifier.size(4.dp).clip(CircleShape).background(tint.copy(alpha = 0.6f))
                        )
                        Spacer(Modifier.width(Dimens.space2))
                        // 资料名多为完整公文标题（40+ 字），单行会被截成看不出差别的一小段，
                        // 放开到两行让用户至少能分辨是哪一份资料
                        Text(s, fontSize = 11.5.sp, color = Ink2, lineHeight = 16.sp,
                            modifier = Modifier.weight(1f).then(
                                if (onSourceClick != null) Modifier.clickable { onSourceClick(index) }
                                else Modifier), maxLines = 2,
                            overflow = TextOverflow.Ellipsis)
                        if (onSourceClick != null) Text("查看原文 →", fontSize = 11.sp,
                            color = tint, modifier = Modifier.clickable { onSourceClick(index) })
                    }
                }
            }
        }
    }
}

/** 上下文要素行：label 弱、value 强，用于任务上下文卡 */
@Composable
fun ContextFact(label: String, value: String, modifier: Modifier = Modifier) {
    Row(modifier.fillMaxWidth().padding(vertical = 4.dp),
        verticalAlignment = Alignment.Top) {
        Text(label, fontSize = 11.5.sp, color = Muted, modifier = Modifier.width(72.dp))
        Text(value.ifBlank { "待补充" }, fontSize = 12.5.sp,
            color = if (value.isBlank()) Muted2 else Ink,
            modifier = Modifier.weight(1f), lineHeight = 18.sp, maxLines = 2,
            overflow = TextOverflow.Ellipsis)
    }
}

/** 上下文模块容器：白底 + 极浅描边，带小标题 */
@Composable
fun ContextBlock(
    title: String,
    modifier: Modifier = Modifier,
    icon: ImageVector? = null,
    tint: Color = Primary,
    content: @Composable ColumnScope.() -> Unit,
) {
    val shape = RoundedCornerShape(Dimens.radiusMd)
    Column(
        modifier.fillMaxWidth().clip(shape).background(Surface)
            .border(1.dp, LineSubtle, shape).padding(Dimens.space4),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            if (icon != null) {
                Icon(icon, contentDescription = null, tint = tint,
                    modifier = Modifier.size(Dimens.iconXs))
                Spacer(Modifier.width(Dimens.space1))
            }
            Text(title, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = Ink,
                modifier = Modifier.weight(1f))
        }
        Spacer(Modifier.height(Dimens.space2))
        content()
    }
}

/** 文档状态条：版本 / 字数 / 状态 */
@Composable
fun DocumentStatusBar(
    left: String,
    items: List<Pair<String, Color>> = emptyList(),
    modifier: Modifier = Modifier,
) {
    Row(
        modifier.fillMaxWidth().padding(vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(left, fontSize = 12.sp, color = Muted)
        items.forEach { (t, c) ->
            Spacer(Modifier.width(Dimens.space3))
            Box(Modifier.size(3.dp).clip(CircleShape).background(Line))
            Spacer(Modifier.width(Dimens.space3))
            Text(t, fontSize = 12.sp, color = c)
        }
        Spacer(Modifier.weight(1f))
    }
}

/** 大号 AI 主视觉条（智能写作入口 / 空状态） */
@Composable
fun AiHeroStrip(
    title: String,
    subtitle: String,
    modifier: Modifier = Modifier,
    icon: ImageVector,
    action: (@Composable () -> Unit)? = null,
) {
    val shape = RoundedCornerShape(Dimens.radiusXl)
    Box(
        modifier.fillMaxWidth().clip(shape)
            .background(Brush.linearGradient(listOf(AiSoft, SurfaceTonal)))
            .border(1.dp, AiSoftStrong, shape),
    ) {
        Row(
            Modifier.fillMaxWidth().padding(Dimens.space6),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                Modifier.size(52.dp).clip(RoundedCornerShape(Dimens.radiusLg))
                    .background(Brush.linearGradient(listOf(AiIndigo, Primary))),
                contentAlignment = Alignment.Center,
            ) {
                Icon(icon, contentDescription = null, tint = OnPrimaryText,
                    modifier = Modifier.size(Dimens.iconLg))
            }
            Spacer(Modifier.width(Dimens.space4))
            Column(Modifier.weight(1f)) {
                Text(title, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = Ink)
                Spacer(Modifier.height(Dimens.space1))
                Text(subtitle, fontSize = 12.5.sp, color = Ink2, lineHeight = 19.sp)
            }
            if (action != null) {
                Spacer(Modifier.width(Dimens.space4))
                action()
            }
        }
    }
}

/** 未使用的兼容色导出 */
val AiSurfaceTonal: Color = SurfaceTonal
val AiSurfaceDeep: Color = SurfaceDeep
val AiMuted: Color = Muted
