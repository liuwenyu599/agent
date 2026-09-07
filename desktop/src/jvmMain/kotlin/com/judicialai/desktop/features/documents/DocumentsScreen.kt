package com.judicialai.desktop.features.documents

import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.Button
import androidx.compose.material.Divider
import androidx.compose.material.MaterialTheme
import androidx.compose.material.OutlinedButton
import androidx.compose.material.OutlinedTextField
import androidx.compose.material.Text
import androidx.compose.material.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.judicialai.desktop.data.Repositories
import com.judicialai.desktop.core.platform.pickSaveFile
import com.judicialai.desktop.core.utils.arr
import com.judicialai.desktop.core.utils.int
import com.judicialai.desktop.core.utils.obj
import com.judicialai.desktop.core.utils.str
import com.judicialai.desktop.design.components.AppCard
import com.judicialai.desktop.design.components.EmptyView
import com.judicialai.desktop.design.components.ErrorText
import com.judicialai.desktop.design.components.LoadingView

/** 我的文档：草稿列表 + 在线编辑 + 版本管理 + 导出 Word。 */
@Composable
fun DocumentsScreen() {
    val vm = remember { DocumentsViewModel(Repositories.documents) }
    LaunchedEffect(Unit) { vm.refresh() }

    Row(Modifier.fillMaxSize().padding(16.dp), horizontalArrangement = Arrangement.spacedBy(16.dp)) {
        // 左：文档列表
        AppCard(Modifier.width(300.dp).fillMaxHeight()) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("我的文档", style = MaterialTheme.typography.h6, fontWeight = FontWeight.Bold)
                Spacer(Modifier.weight(1f))
                TextButton(onClick = { vm.createNew() }) { Text("新建") }
                TextButton(onClick = { vm.refresh() }) { Text("刷新") }
            }
            Divider()
            if (vm.documents.isEmpty()) {
                EmptyView("暂无文档，在智能写作中生成后会自动保存到这里")
            } else LazyColumn {
                items(vm.documents) { d ->
                    val id = d["id"].str()
                    Column(
                        Modifier.fillMaxWidth()
                            .clickable { vm.open(id) }
                            .padding(vertical = 8.dp),
                    ) {
                        Text(d["title"].str().ifBlank { "未命名文档" },
                            style = MaterialTheme.typography.body1,
                            fontWeight = if (id == vm.currentId) FontWeight.Bold else FontWeight.Normal)
                        val meta = listOfNotNull(
                            d["document_number"].str().ifBlank { null },
                            "v${d["current_version"].int()}",
                            d["status"].str().ifBlank { null },
                        ).joinToString(" · ")
                        Text(meta, style = MaterialTheme.typography.body2,
                            color = MaterialTheme.colors.onSurface.copy(alpha = 0.6f))
                    }
                    Divider()
                }
            }
        }

        // 右：编辑 / 预览
        AppCard(Modifier.weight(1f).fillMaxHeight()) {
            if (vm.busy) LoadingView()
            ErrorText(vm.status)

            val preview = vm.previewVersion
            if (preview != null) {
                // 历史版本只读预览
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("历史版本 v${preview["version_no"].int()}（只读）",
                        style = MaterialTheme.typography.subtitle1)
                    Spacer(Modifier.weight(1f))
                    TextButton(onClick = { vm.closePreview() }) { Text("返回当前版本") }
                }
                Text(preview["content"].str(),
                    Modifier.weight(1f).verticalScroll(rememberScrollState()),
                    style = MaterialTheme.typography.body1)
            } else {
                OutlinedTextField(
                    value = vm.title, onValueChange = { vm.title = it },
                    label = { Text("标题") }, modifier = Modifier.fillMaxWidth(),
                )
                if (vm.docNumber.isNotBlank() || vm.docDate.isNotBlank()) {
                    Text(
                        listOfNotNull(
                            vm.docNumber.ifBlank { null },
                            vm.docDate.ifBlank { null },
                            if (vm.currentVersion > 0) "当前版本 v${vm.currentVersion}" else null,
                        ).joinToString(" · "),
                        style = MaterialTheme.typography.body2,
                        color = MaterialTheme.colors.onSurface.copy(alpha = 0.6f),
                    )
                }
                OutlinedTextField(
                    value = vm.content, onValueChange = { vm.content = it },
                    label = { Text("正文（每次保存生成一个新版本）") },
                    modifier = Modifier.fillMaxWidth().weight(1f),
                )

                // 质检 / 内容核查摘要
                vm.quality?.let { q ->
                    val level = q["level"].str()
                    val issues = q["issues"].arr().map { it.obj()?.get("message")?.str() ?: "" }
                        .filter { it.isNotBlank() }
                    Text("质检等级：$level" + if (issues.isNotEmpty()) "（${issues.size} 项提示）" else "",
                        style = MaterialTheme.typography.body2)
                    issues.take(5).forEach {
                        Text("· $it", style = MaterialTheme.typography.body2,
                            color = MaterialTheme.colors.onSurface.copy(alpha = 0.6f))
                    }
                }
                vm.contentCheck?.let { cc ->
                    val unverified = cc["unverified"].arr().map { it.str() }.filter { it.isNotBlank() }
                    if (unverified.isNotEmpty()) {
                        Text("内容核查未核实引用：${unverified.joinToString("、")}",
                            style = MaterialTheme.typography.body2,
                            color = MaterialTheme.colors.error)
                    }
                }

                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    Button(onClick = { vm.save(null) }, enabled = !vm.busy && vm.content.isNotBlank()) {
                        Text(if (vm.currentId == null) "创建文档" else "保存新版本")
                    }
                    OutlinedButton(
                        onClick = { pickSaveFile("${vm.title.ifBlank { "公文" }}.docx")?.let { vm.export(it) } },
                        enabled = !vm.busy && vm.currentId != null,
                    ) { Text("导出 Word") }
                    OutlinedButton(onClick = { vm.delete() },
                        enabled = !vm.busy && vm.currentId != null) { Text("删除") }
                }
                if (vm.versions.isNotEmpty()) {
                    Text("历史版本：", style = MaterialTheme.typography.body2)
                    Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                        vm.versions.forEach { v ->
                            val no = v["version_no"].int()
                            TextButton(onClick = { vm.previewVersion(no) }) { Text("v$no") }
                        }
                    }
                }
            }
        }
    }
}
