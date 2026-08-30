package com.judicialai.desktop.features.knowledge

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.AlertDialog
import androidx.compose.material.Button
import androidx.compose.material.ButtonDefaults
import androidx.compose.material.Card
import androidx.compose.material.Divider
import androidx.compose.material.Icon
import androidx.compose.material.OutlinedTextField
import androidx.compose.material.Text
import androidx.compose.material.TextButton
import androidx.compose.material.TextFieldDefaults
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.List
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.core.platform.pickFiles
import com.judicialai.desktop.core.utils.int
import com.judicialai.desktop.core.utils.str
import com.judicialai.desktop.data.Repositories
import com.judicialai.desktop.design.theme.EpDanger
import com.judicialai.desktop.design.theme.EpPrimary
import com.judicialai.desktop.design.theme.EpSuccess
import com.judicialai.desktop.design.theme.Surface
import com.judicialai.desktop.design.theme.TextPlaceholder
import com.judicialai.desktop.design.theme.TextPrimary
import com.judicialai.desktop.design.theme.TextRegular
import com.judicialai.desktop.design.theme.TextSecondary

/** 知识库：1:1 还原 Web KnowledgeView（统计条 + 筛选 + 表格）+ 详情视图 */
@Composable
fun KnowledgeScreen() {
    val vm = remember { KnowledgeViewModel(Repositories.knowledge) }
    LaunchedEffect(Unit) { vm.loadKbs(); vm.loadStats() }

    val current = vm.currentKb
    if (current != null) {
        KnowledgeDetail(vm)
    } else {
        KnowledgeList(vm)
    }
}

@Composable
private fun KnowledgeList(vm: KnowledgeViewModel) {
    var search by remember { mutableStateOf("") }
    var showCreate by remember { mutableStateOf(false) }

    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        // 统计条
        Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            vm.stats.forEach { (label, value) ->
                Card(Modifier.weight(1f), shape = RoundedCornerShape(8.dp), elevation = 0.dp) {
                    Column(
                        Modifier.fillMaxWidth().padding(16.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) {
                        Text(value, fontSize = 26.sp, fontWeight = FontWeight.Bold,
                            color = EpPrimary)
                        Spacer(Modifier.height(8.dp))
                        Text(label, fontSize = 13.sp, color = TextSecondary)
                    }
                }
            }
        }

        // 筛选
        Card(shape = RoundedCornerShape(8.dp), elevation = 0.dp) {
            Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                OutlinedTextField(
                    value = search, onValueChange = { search = it },
                    placeholder = { Text("搜索知识库", fontSize = 13.sp) },
                    leadingIcon = { Icon(Icons.Default.Search, null, tint = TextSecondary) },
                    singleLine = true,
                    modifier = Modifier.width(220.dp).height(52.dp),
                    colors = TextFieldDefaults.outlinedTextFieldColors(
                        focusedBorderColor = EpPrimary, cursorColor = EpPrimary),
                )
                Spacer(Modifier.weight(1f))
                Button(onClick = { showCreate = true },
                    colors = ButtonDefaults.buttonColors(backgroundColor = EpPrimary)) {
                    Icon(Icons.Default.Add, null, tint = Color.White,
                        modifier = Modifier.size(16.dp))
                    Text("新建知识库", color = Color.White, fontSize = 13.sp)
                }
                TextButton(onClick = { vm.loadKbs() }) {
                    Icon(Icons.Default.Refresh, null, tint = TextRegular,
                        modifier = Modifier.size(16.dp))
                    Text("刷新", color = TextRegular, fontSize = 13.sp)
                }
            }
        }

        // 表格
        Card(shape = RoundedCornerShape(8.dp), elevation = 0.dp) {
            Column {
                Row(
                    Modifier.fillMaxWidth().background(Color(0xFFFAFAFA))
                        .padding(horizontal = 20.dp, vertical = 12.dp),
                ) {
                    Text("#", Modifier.width(50.dp), fontSize = 13.sp, color = TextSecondary)
                    Text("知识库名称", Modifier.weight(2f), fontSize = 13.sp, color = TextSecondary)
                    Text("类型", Modifier.width(90.dp), fontSize = 13.sp, color = TextSecondary)
                    Text("文档数", Modifier.width(90.dp), fontSize = 13.sp, color = TextSecondary)
                    Text("创建时间", Modifier.width(160.dp), fontSize = 13.sp, color = TextSecondary)
                    Text("操作", Modifier.width(180.dp), fontSize = 13.sp, color = TextSecondary)
                }
                val filtered = vm.kbs.filter {
                    search.isBlank() || it["name"].str().contains(search, true)
                }
                if (filtered.isEmpty()) {
                    Box(Modifier.fillMaxWidth().padding(40.dp),
                        contentAlignment = Alignment.Center) {
                        Text("暂无知识库", color = TextSecondary, fontSize = 13.sp)
                    }
                }
                filtered.forEachIndexed { i, kb ->
                    Row(
                        Modifier.fillMaxWidth()
                            .clickable { vm.select(kb) }
                            .padding(horizontal = 20.dp, vertical = 12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text("${i + 1}", Modifier.width(50.dp), fontSize = 13.sp,
                            color = TextRegular)
                        Row(Modifier.weight(2f), verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                            Icon(Icons.Default.List, null, tint = EpPrimary,
                                modifier = Modifier.size(20.dp))
                            Column {
                                Text(kb["name"].str(), fontSize = 14.sp,
                                    fontWeight = FontWeight.Medium, color = TextPrimary)
                                Text(kb["description"].str().ifBlank { "暂无描述" },
                                    fontSize = 12.sp, color = TextSecondary,
                                    maxLines = 1, overflow = TextOverflow.Ellipsis)
                            }
                        }
                        Box(Modifier.width(90.dp)) {
                            KbTag(if (kb["type"].str() == "public") "公共" else "个人",
                                kb["type"].str() == "public")
                        }
                        Text("${kb["doc_count"].int()}", Modifier.width(90.dp),
                            fontSize = 13.sp, color = EpSuccess)
                        Text(kb["created_at"].str().take(10), Modifier.width(160.dp),
                            fontSize = 13.sp, color = TextRegular)
                        Row(Modifier.width(180.dp)) {
                            TextButton(onClick = { vm.select(kb) }) {
                                Text("查看", color = EpPrimary, fontSize = 13.sp)
                            }
                            TextButton(onClick = { vm.deleteKb(kb["id"].str()) }) {
                                Text("删除", color = EpDanger, fontSize = 13.sp)
                            }
                        }
                    }
                    Divider(color = Color(0xFFF2F4F8))
                }
            }
        }
        vm.status?.let { Text(it, fontSize = 12.sp, color = TextSecondary) }
    }

    if (showCreate) {
        var name by remember { mutableStateOf("") }
        var desc by remember { mutableStateOf("") }
        AlertDialog(
            onDismissRequest = { showCreate = false },
            title = { Text("新建知识库") },
            text = {
                Column {
                    OutlinedTextField(value = name, onValueChange = { name = it },
                        label = { Text("名称") }, singleLine = true,
                        modifier = Modifier.fillMaxWidth())
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(value = desc, onValueChange = { desc = it },
                        label = { Text("描述") }, modifier = Modifier.fillMaxWidth())
                }
            },
            confirmButton = {
                Button(onClick = {
                    if (name.isNotBlank()) { vm.create(name, desc); showCreate = false }
                }, colors = ButtonDefaults.buttonColors(backgroundColor = EpPrimary)) {
                    Text("创建", color = Color.White)
                }
            },
            dismissButton = { TextButton(onClick = { showCreate = false }) { Text("取消") } },
        )
    }
}

/** 知识库详情：对应 Web KnowledgeDetailView（返回头 + 文档表格 + 上传） */
@Composable
private fun KnowledgeDetail(vm: KnowledgeViewModel) {
    val kb = vm.currentKb ?: return
    Column(Modifier.fillMaxSize().padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            TextButton(onClick = { vm.back() }) {
                Icon(Icons.Default.ArrowBack, null, tint = EpPrimary,
                    modifier = Modifier.size(16.dp))
                Text("返回", color = EpPrimary)
            }
            Text(kb["name"].str(), fontSize = 18.sp, fontWeight = FontWeight.SemiBold,
                color = TextPrimary)
            Spacer(Modifier.weight(1f))
            Button(
                onClick = { vm.upload(pickFiles("上传文档", multi = true)) },
                enabled = !vm.busy,
                colors = ButtonDefaults.buttonColors(backgroundColor = EpPrimary),
            ) {
                Icon(Icons.Default.Add, null, tint = Color.White,
                    modifier = Modifier.size(16.dp))
                Text(if (vm.busy) "上传中…" else "上传文档", color = Color.White,
                    fontSize = 13.sp)
            }
        }

        Card(shape = RoundedCornerShape(8.dp), elevation = 0.dp,
            modifier = Modifier.fillMaxWidth().weight(1f)) {
            Column {
                Row(Modifier.fillMaxWidth().background(Color(0xFFFAFAFA))
                    .padding(horizontal = 20.dp, vertical = 12.dp)) {
                    Text("文档标题", Modifier.weight(2f), fontSize = 13.sp, color = TextSecondary)
                    Text("类型", Modifier.width(100.dp), fontSize = 13.sp, color = TextSecondary)
                    Text("状态", Modifier.width(100.dp), fontSize = 13.sp, color = TextSecondary)
                    Text("上传时间", Modifier.width(160.dp), fontSize = 13.sp, color = TextSecondary)
                    Text("操作", Modifier.width(100.dp), fontSize = 13.sp, color = TextSecondary)
                }
                Column(Modifier.verticalScroll(rememberScrollState())) {
                    if (vm.docs.isEmpty()) {
                        Box(Modifier.fillMaxWidth().padding(40.dp),
                            contentAlignment = Alignment.Center) {
                            Text("暂无文档，点击右上角上传", color = TextSecondary, fontSize = 13.sp)
                        }
                    }
                    vm.docs.forEach { d ->
                        Row(Modifier.fillMaxWidth()
                            .padding(horizontal = 20.dp, vertical = 12.dp),
                            verticalAlignment = Alignment.CenterVertically) {
                            Text(d["title"].str().ifBlank { d["filename"].str() },
                                Modifier.weight(2f), fontSize = 14.sp, color = TextPrimary,
                                maxLines = 1, overflow = TextOverflow.Ellipsis)
                            Text(d["doc_type"].str().ifBlank { "-" }, Modifier.width(100.dp),
                                fontSize = 13.sp, color = TextRegular)
                            Box(Modifier.width(100.dp)) {
                                val s = d["status"].str()
                                KbTag(
                                    when (s) {
                                        "published" -> "已发布"; "pending" -> "待审核"
                                        "rejected" -> "已驳回"; else -> s.ifBlank { "-" }
                                    },
                                    s == "published",
                                )
                            }
                            Text(d["created_at"].str().take(16).replace("T", " "),
                                Modifier.width(160.dp), fontSize = 13.sp, color = TextRegular)
                            TextButton(onClick = { vm.deleteDocument(d["id"].str()) },
                                modifier = Modifier.width(100.dp)) {
                                Icon(Icons.Default.Delete, null, tint = EpDanger,
                                    modifier = Modifier.size(16.dp))
                            }
                        }
                        Divider(color = Color(0xFFF2F4F8))
                    }
                }
            }
        }
        vm.status?.let { Text(it, fontSize = 12.sp, color = TextSecondary) }
    }
}

@Composable
private fun KbTag(text: String, green: Boolean) {
    val color = if (green) EpSuccess else TextSecondary
    Box(
        Modifier.clip(RoundedCornerShape(4.dp))
            .background(color.copy(alpha = 0.12f))
            .padding(horizontal = 8.dp, vertical = 2.dp),
    ) { Text(text, fontSize = 11.sp, color = color) }
}

