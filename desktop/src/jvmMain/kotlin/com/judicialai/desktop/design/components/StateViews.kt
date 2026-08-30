package com.judicialai.desktop.design.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.CircularProgressIndicator
import androidx.compose.material.MaterialTheme
import androidx.compose.material.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.judicialai.desktop.design.theme.SecondaryText

@Composable
fun LoadingView(text: String = "加载中…") {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(10.dp)) {
            CircularProgressIndicator(Modifier.size(28.dp), strokeWidth = 2.dp)
            Text(text, style = MaterialTheme.typography.caption, color = SecondaryText)
        }
    }
}

@Composable
fun EmptyView(text: String) {
    Box(Modifier.fillMaxSize().padding(24.dp), contentAlignment = Alignment.Center) {
        Text(text, style = MaterialTheme.typography.body2, color = SecondaryText)
    }
}

@Composable
fun ErrorText(message: String?, modifier: Modifier = Modifier) {
    message?.let {
        Text(it, style = MaterialTheme.typography.caption,
            color = MaterialTheme.colors.error, modifier = modifier)
    }
}

