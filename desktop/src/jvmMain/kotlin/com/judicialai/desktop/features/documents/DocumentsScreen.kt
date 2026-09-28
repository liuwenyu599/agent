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
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.data.Repositories
import com.judicialai.desktop.core.platform.pickSaveFile
import com.judicialai.desktop.core.utils.arr
import com.judicialai.desktop.core.utils.int
import com.judicialai.desktop.core.utils.obj
import com.judicialai.desktop.core.utils.str
import com.judicialai.desktop.design.components.AppButton
import com.judicialai.desktop.design.components.AppButtonKind
import com.judicialai.desktop.design.components.AppCard
import com.judicialai.desktop.design.components.AppDialog
import com.judicialai.desktop.design.components.EmptyView
import com.judicialai.desktop.design.components.ErrorText
import com.judicialai.desktop.design.components.LoadingView
import com.judicialai.desktop.design.components.MarkdownView
import com.judicialai.desktop.design.theme.Ink
import com.judicialai.desktop.design.theme.Muted

/**
 * 我的文档：草稿列表 + 在线编辑 + 版本管理 + 导出 Word。
 *
 * 右侧编辑台默认是「预览」：正文按 Markdown 轻量渲染（标题/粗体/列表），
 * 屏上就能看到与导出 docx 对应的层级版式，不再是满屏无格式 txt；
 * 点「编辑正文」切回源文编辑框，改完「完成编辑」回到预览。
 */
@Composable
fun DocumentsScreen() {
    val vm = remember { DocumentsViewModel(Repositories.documents) }
    var confirmDelete by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) {
        vm.refresh()
        // 历史记录「继续」带过来的文档 id：打开这一条后用完即清，避免下次进页面又自动打开
        AppState.pendingDocumentId?.let { id ->
            AppState.pendingDocumentId = null
            vm.open(id)
        }
    }

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
                // 历史版本只读预览：同样按格式渲染，不是裸 txt
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("历史版本 v${preview["version_no"].int()}（只读）",
                        style = MaterialTheme.typography.subtitle1)
                    Spacer(Modifier.weight(1f))
                    TextButton(onClick = { vm.closePreview() }) { Text("返回当前版本") }
                }
                Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
                    MarkdownView(preview["content"].str())
                }
            } else {
                // 编辑台：默认预览（带格式），「编辑正文」切到源文编辑框。
                // 按 currentId 记忆开关：换一篇文档时回到预览态。
                var editing by remember(vm.currentId) { mutableStateOf(false) }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    if (editing) {
                        OutlinedTextField(
                            value = vm.title, onValueChange = { vm.title = it },
                            label = { Text("标题") }, modifier = Modifier.weight(1f),
                        )
                    } else {
                        Text(vm.title.ifBlank { "未命名文档" },
                            style = MaterialTheme.typography.h6, color = Ink,
                            modifier = Modifier.weight(1f))
                    }
                    Spacer(Modifier.width(8.dp))
                    TextButton(onClick = { editing = !editing }) {
                        Text(if (editing) "完成编辑" else "编辑正文")
                    }
                }
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
                if (editing) {
                    OutlinedTextField(
                        value = vm.content, onValueChange = { vm.content = it },
                        label = { Text("正文（每次保存生成一个新版本）") },
                        modifier = Modifier.fillMaxWidth().weight(1f),
                    )
                } else {
                    Column(
                        Modifier.fillMaxWidth().weight(1f)
                            .verticalScroll(rememberScrollState()),
                    ) {
                        if (vm.content.isBlank()) {
                            Text("（暂无正文，点右上角「编辑正文」开始撰写）",
                                fontSize = 13.sp, color = Muted)
                        } else {
                            MarkdownView(vm.content)
                        }
                    }
                }

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
                    OutlinedButton(onClick = { confirmDelete = true },
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

    if (confirmDelete && vm.currentId != null) {
        AppDialog(
            onDismissRequest = { confirmDelete = false },
            title = "删除文档",
            subtitle = "删除后该文档及历史版本将无法从“我的文档”继续使用。",
            width = 460.dp,
            actions = {
                AppButton("取消", onClick = { confirmDelete = false }, kind = AppButtonKind.SECONDARY)
                Spacer(Modifier.width(8.dp))
                AppButton("确认删除", onClick = {
                    confirmDelete = false
                    vm.delete()
                }, kind = AppButtonKind.DANGER)
            },
        ) {
            Text(vm.title.ifBlank { "未命名文档" }, style = MaterialTheme.typography.body1)
        }
    }
}
