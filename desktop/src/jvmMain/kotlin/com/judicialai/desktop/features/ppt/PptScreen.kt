package com.judicialai.desktop.features.ppt

import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.Button
import androidx.compose.material.ButtonDefaults
import androidx.compose.material.Card
import androidx.compose.material.Icon
import androidx.compose.material.IconButton
import androidx.compose.material.MaterialTheme
import androidx.compose.material.OutlinedButton
import androidx.compose.material.OutlinedTextField
import androidx.compose.material.Tab
import androidx.compose.material.TabRow
import androidx.compose.material.Text
import androidx.compose.material.TextButton
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.dp
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.core.platform.pickFiles
import com.judicialai.desktop.core.platform.pickSaveFile
import com.judicialai.desktop.core.platform.rememberServerImage
import com.judicialai.desktop.core.utils.str
import com.judicialai.desktop.data.Repositories
import com.judicialai.desktop.design.theme.SecondaryText

/** PPT 助手（对应 Web PptView + PptTemplateLib）：创建 / 我的 PPT / 模板库 */
@Composable
fun PptScreen() {
    val vm = remember { PptViewModel(Repositories.ppt) }
    var tab by remember { mutableStateOf(0) }

    LaunchedEffect(Unit) { vm.loadTemplates(); vm.loadDocuments() }

    Column(Modifier.fillMaxSize()) {
        TabRow(selectedTabIndex = tab) {
            Tab(tab == 0, { tab = 0 }) { Text("创建 PPT", Modifier.padding(12.dp)) }
            Tab(tab == 1, { tab = 1 }) { Text("我的 PPT", Modifier.padding(12.dp)) }
            Tab(tab == 2, { tab = 2 }) { Text("模板库", Modifier.padding(12.dp)) }
        }
        Column(Modifier.padding(12.dp)) {
            when (tab) {
                0 -> PptCreatePane(vm)
                1 -> PptDocsPane(vm)
                else -> PptTemplatesPane(vm)
            }
        }
    }
}

@Composable
private fun sel(selected: Boolean) = ButtonDefaults.outlinedButtonColors(
    backgroundColor = if (selected) MaterialTheme.colors.primary.copy(alpha = 0.12f)
    else Color.Transparent)

@Composable
private fun PptCreatePane(vm: PptViewModel) {
    var topic by remember { mutableStateOf("") }
    var content by remember { mutableStateOf("") }
    var slideCount by remember { mutableStateOf("10") }
    var audience by remember { mutableStateOf("") }
    var scene by remember { mutableStateOf("") }
    var sourceType by remember { mutableStateOf("topic") }

    Column(Modifier.verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically) {
            Text("方式：")
            OutlinedButton(onClick = { sourceType = "topic" },
                colors = sel(sourceType == "topic")) { Text("主题生成") }
            OutlinedButton(onClick = { sourceType = "content" },
                colors = sel(sourceType == "content")) { Text("文档提炼") }
        }

        if (sourceType == "topic") {
            OutlinedTextField(topic, { topic = it },
                label = { Text("主题，如：社区矫正工作汇报") }, modifier = Modifier.fillMaxWidth())
        } else {
            OutlinedTextField(content, { content = it },
                label = { Text("粘贴文档内容，AI 提炼成大纲") },
                modifier = Modifier.fillMaxWidth().height(140.dp))
        }

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(slideCount, { slideCount = it.filter(Char::isDigit) },
                label = { Text("页数") }, modifier = Modifier.weight(1f))
            OutlinedTextField(audience, { audience = it },
                label = { Text("受众（可选）") }, modifier = Modifier.weight(1f))
            OutlinedTextField(scene, { scene = it },
                label = { Text("场景（可选）") }, modifier = Modifier.weight(1f))
        }

        Text("选择模板", style = MaterialTheme.typography.subtitle2)
        Row(Modifier.fillMaxWidth().height(130.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            vm.templates.take(6).forEach { t ->
                val tid = t["id"].str()
                val selected = tid == vm.templateId
                Card(
                    Modifier.width(180.dp).fillMaxHeight(),
                    elevation = if (selected) 6.dp else 1.dp,
                    backgroundColor = if (selected)
                        MaterialTheme.colors.primary.copy(alpha = 0.10f)
                    else MaterialTheme.colors.surface,
                ) {
                    TextButton(onClick = { vm.templateId = tid }, modifier = Modifier.fillMaxSize()) {
                        Column(Modifier.fillMaxSize()) {
                            val img = rememberServerImage(AppState.api,
                                t["preview_url"].str().ifBlank { null })
                            if (img != null) {
                                Image(img, contentDescription = t["name"].str(),
                                    modifier = Modifier.fillMaxWidth().weight(1f),
                                    contentScale = ContentScale.Crop)
                            } else {
                                Box(Modifier.fillMaxWidth().weight(1f),
                                    contentAlignment = Alignment.Center) {
                                    Text(t["name"].str(), style = MaterialTheme.typography.caption)
                                }
                            }
                            Text(t["name"].str(), style = MaterialTheme.typography.caption,
                                maxLines = 1, modifier = Modifier.padding(4.dp))
                        }
                    }
                }
            }
            if (vm.templates.isEmpty()) {
                Text("模板加载中或为空，可到“模板库”上传。", style = MaterialTheme.typography.caption,
                    color = SecondaryText, modifier = Modifier.align(Alignment.CenterVertically))
            }
        }

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(
                enabled = !vm.busy &&
                    (if (sourceType == "topic") topic.isNotBlank() else content.isNotBlank()),
                onClick = {
                    vm.createOutline(sourceType, topic, content,
                        slideCount.toIntOrNull() ?: 10, audience, scene)
                }) { Text("1. 生成大纲") }
            Button(
                enabled = !vm.busy && vm.docId != null && vm.outlineText.isNotBlank(),
                onClick = { vm.generate() }) { Text("2. 生成 PPT") }
        }

        if (vm.outlineText.isNotBlank()) {
            OutlinedTextField(vm.outlineText, { vm.outlineText = it },
                label = { Text("大纲（JSON，可编辑）") },
                modifier = Modifier.fillMaxWidth().height(200.dp))
        }

        PptStatus(vm)
    }
}

@Composable
private fun PptDocsPane(vm: PptViewModel) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("我的 PPT", style = MaterialTheme.typography.subtitle1,
                modifier = Modifier.weight(1f))
            IconButton(onClick = { vm.loadDocuments() }) {
                Icon(Icons.Default.Refresh, "刷新")
            }
        }
        PptStatus(vm)
        LazyColumn(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            items(vm.documents) { d ->
                val id = d["id"].str()
                Card(Modifier.fillMaxWidth(), elevation = 1.dp) {
                    Row(Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(d["title"].str().ifBlank { d["topic"].str() },
                                style = MaterialTheme.typography.subtitle2)
                            Text(d["created_at"].str(), style = MaterialTheme.typography.caption,
                                color = SecondaryText)
                        }
                        Button(enabled = vm.downloadingId != id, onClick = {
                            val target = pickSaveFile(
                                d["title"].str().ifBlank { "演示文稿" } + ".pptx") ?: return@Button
                            vm.download(id, d["title"].str(), target)
                        }) { Text(if (vm.downloadingId == id) "下载中…" else "下载") }
                        Spacer(Modifier.width(4.dp))
                        IconButton(onClick = { vm.deleteDocument(id) }) {
                            Icon(Icons.Default.Delete, "删除", tint = MaterialTheme.colors.error)
                        }
                    }
                }
            }
            if (vm.documents.isEmpty()) item {
                Text("暂无 PPT，先到“创建 PPT”生成。", style = MaterialTheme.typography.caption,
                    color = SecondaryText)
            }
        }
    }
}

@Composable
private fun PptTemplatesPane(vm: PptViewModel) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("模板库（上传后自动学习版式与风格）", style = MaterialTheme.typography.subtitle1,
                modifier = Modifier.weight(1f))
            IconButton(onClick = { vm.loadTemplates() }) {
                Icon(Icons.Default.Refresh, "刷新")
            }
            Button(enabled = !vm.busy, onClick = {
                pickFiles("选择 pptx 模板").firstOrNull()?.let { vm.uploadTemplate(it) }
            }) { Text(if (vm.busy) "学习中…" else "上传模板") }
        }
        PptStatus(vm)
        LazyVerticalGrid(columns = GridCells.Adaptive(200.dp),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)) {
            items(vm.templates) { t ->
                Card(elevation = 2.dp) {
                    Column {
                        val img = rememberServerImage(AppState.api,
                            t["preview_url"].str().ifBlank { null })
                        if (img != null) {
                            Image(img, contentDescription = t["name"].str(),
                                modifier = Modifier.fillMaxWidth().height(110.dp),
                                contentScale = ContentScale.Crop)
                        } else {
                            Box(Modifier.fillMaxWidth().height(110.dp),
                                contentAlignment = Alignment.Center) {
                                Text("无预览", style = MaterialTheme.typography.caption,
                                    color = SecondaryText)
                            }
                        }
                        Row(Modifier.padding(8.dp),
                            verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text(t["name"].str(), style = MaterialTheme.typography.subtitle2,
                                    maxLines = 1)
                                Text(t["layout_count"].str().ifBlank { "?" } + " 种版式",
                                    style = MaterialTheme.typography.caption, color = SecondaryText)
                            }
                            IconButton(onClick = { vm.deleteTemplate(t["id"].str()) }) {
                                Icon(Icons.Default.Delete, "删除",
                                    tint = MaterialTheme.colors.error)
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun PptStatus(vm: PptViewModel) {
    vm.status?.let {
        Text(it, style = MaterialTheme.typography.caption,
            color = if (it.contains("完成") || it.contains("已保存")) MaterialTheme.colors.primary
            else MaterialTheme.colors.error)
    }
}

