package com.judicialai.desktop.design.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.design.theme.Ink
import com.judicialai.desktop.design.theme.Muted
import com.judicialai.desktop.design.theme.Primary
import com.judicialai.desktop.design.theme.SurfaceTonal

/**
 * 对话气泡（共享组件）：一来一回的两个阵营，靠对齐 + 底色 + 宽度共同区分。
 *
 * 关键点是**按内容自适应宽度**（[maxWidth] 封顶）而不是 ``fillMaxWidth`` 撑满整行。
 * 撑满之后，用户短句也会拉出一整条通栏色块，对话失去节奏感，看起来像一叠表单卡片——
 * 这是知识问答页原先「不像聊天」的主要观感来源。
 *
 * 设计系统里凡一处渲染「用户 / 助手」两类消息的地方都应复用它，避免各写一套：
 * - 历史记录的对话回看（ChatViewDialog）
 * - 知识库问答（QaMessageCard）
 */
@Composable
fun ChatBubble(
    isUser: Boolean,
    label: String,
    modifier: Modifier = Modifier,
    maxWidth: Dp = 460.dp,
    content: @Composable () -> Unit,
) {
    // 靠说话人那一侧的角收窄，气泡朝向说话人，进一步强化对话感
    val shape = RoundedCornerShape(
        topStart = if (isUser) 10.dp else 2.dp,
        topEnd = if (isUser) 2.dp else 10.dp,
        bottomStart = 10.dp,
        bottomEnd = 10.dp,
    )
    Column(
        modifier.fillMaxWidth(),
        horizontalAlignment = if (isUser) Alignment.End else Alignment.Start,
    ) {
        Text(label, fontSize = 11.sp, color = Muted)
        Spacer(Modifier.height(3.dp))
        Box(
            Modifier.widthIn(max = maxWidth)
                .clip(shape)
                .background(if (isUser) Primary else SurfaceTonal)
                .padding(horizontal = 12.dp, vertical = 8.dp),
        ) {
            content()
        }
    }
}

/**
 * 纯文本对话气泡：[ChatBubble] 的便捷形态，自动按阵营配色。
 *
 * 用户气泡是 Primary 深底，文字必须反白；助手是 tonal 浅底，用常规深字。
 * 这两处颜色很容易写错（尤其后来把 assistant 也改成实底时），由本组件统一负责。
 */
@Composable
fun ChatTextBubble(
    isUser: Boolean,
    label: String,
    text: String,
    modifier: Modifier = Modifier,
    maxWidth: Dp = 460.dp,
) {
    ChatBubble(isUser = isUser, label = label, modifier = modifier, maxWidth = maxWidth) {
        // 回看历史对话时用户多半要摘抄内容，气泡统一支持选中复制
        SelectionContainer {
            Text(
                text,
                fontSize = 13.sp,
                lineHeight = 20.sp,
                color = if (isUser) Color.White else Ink,
            )
        }
    }
}
