package com.judicialai.desktop.design.components

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsHoveredAsState
import androidx.compose.foundation.hoverable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.Card
import androidx.compose.material.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay

enum class ToastType { INFO, SUCCESS, ERROR, WARNING }

data class ToastItem(
    val id: Long,
    val message: String,
    val type: ToastType,
    val createdAt: Long = System.currentTimeMillis(),
)

/** Per-window queue. Keep an instance on WindowSession so parallel windows never share notices. */
class ToastState {
    val items = mutableStateListOf<ToastItem>()

    fun show(message: String, type: ToastType = ToastType.INFO) {
        if (message.isBlank()) return
        items.add(0, ToastItem(System.nanoTime(), message, type))
        while (items.size > 4) items.removeAt(items.lastIndex)
    }

    fun dismiss(id: Long) { items.removeAll { it.id == id } }
}

@Composable
fun ToastHost(state: ToastState, modifier: Modifier = Modifier) {
    Column(modifier, verticalArrangement = Arrangement.spacedBy(8.dp)) {
        state.items.toList().forEach { item ->
            var expanded by remember(item.id) { mutableStateOf(false) }
            val interactions = remember(item.id) { MutableInteractionSource() }
            val hovering by interactions.collectIsHoveredAsState()
            var visible by remember(item.id) { mutableStateOf(true) }
            val alpha by animateFloatAsState(if (visible) 1f else 0f)
            LaunchedEffect(item.id, hovering) {
                if (!hovering) {
                    delay(3700)
                    visible = false
                    delay(300)
                    state.dismiss(item.id)
                }
            }
            Card(
                modifier = Modifier.fillMaxWidth().hoverable(interactions).alpha(alpha)
                    .clickable(interactionSource = interactions, indication = null) {
                        expanded = !expanded
                    },
                elevation = 8.dp,
                backgroundColor = when (item.type) {
                    ToastType.SUCCESS -> Color(0xFFEAF7EF)
                    ToastType.ERROR -> Color(0xFFFFEEEE)
                    ToastType.WARNING -> Color(0xFFFFF5DF)
                    ToastType.INFO -> Color(0xFFEFF4FF)
                },
            ) {
                Text(
                    item.message,
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp),
                    color = Color(0xFF263247), fontSize = 13.sp,
                    maxLines = if (expanded) Int.MAX_VALUE else 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}
