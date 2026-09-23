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
import androidx.compose.foundation.layout.heightIn
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
import androidx.compose.material.RadioButton
import androidx.compose.material.RadioButtonDefaults
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
import com.judicialai.desktop.app.AppState
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
import kotlinx.serialization.json.JsonObject

/** 知识库：统计条（公共/科室/个人/文档总数）+ 筛选 + 表格 + 详情视图 */
@Composable
fun KnowledgeScreen() {
    val vm = remember { KnowledgeViewModel(Repositories.knowledge) }
    LaunchedEffect(Unit) { vm.loadKbs() }

    val current = vm.currentKb
    if (current != null) {
        KnowledgeDetail(vm)
    } else {
        KnowledgeList(vm)
    }

    // 知识库编辑弹窗（管理员：名称 / 描述 / 类型）
    vm.editingKb?.let { kb ->
        KbEditDialog(
            kb = kb,
            onDismiss = { vm.editingKb = null },
            onSave = { name, desc, kbType -> vm.updateKb(kb["id"].str(), name, desc, kbType) },
        )
    }

    // 文档查看 / 编辑弹窗
    if (vm.docDialogId != null) {
        KnowledgeDocDialog(
            title = vm.docDialogTitle,
            content = vm.docDialogContent,
            busy = vm.docDialogBusy,
            onTitleChange = { vm.docDialogTitle = it },
            onContentChange = { vm.docDialogContent = it },
            onSave = { vm.saveDocument() },
            onClose = { vm.closeDocument() },
        )
    }
}

/**
 * 知识库文档查看 / 编辑弹窗。
 * 知识库列表与智能写作「参考材料」共用；保存后后端重新分块并重建检索向量。
 * 无编辑权限的用户保存时会被服务端拒绝并提示。
 */
@Composable
fun KnowledgeDocDialog(
    title: String,
    content: String,
    busy: Boolean,
    onTitleChange: (String) -> Unit,
    onContentChange: (String) -> Unit,
    onSave: () -> Unit,
    onClose: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onClose,
        title = { Text("查看 / 编辑文档", fontWeight = FontWeight.SemiBold) },
        text = {
            Column {
                OutlinedTextField(
                    value = title, onValueChange = onTitleChange,
                    label = { Text("标题") }, singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                    colors = TextFieldDefaults.outlinedTextFieldColors(
                        focusedBorderColor = EpPrimary, cursorColor = EpPrimary),
                )
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = content, onValueChange = onContentChange,
                    label = { Text("正文内容") },
                    modifier = Modifier.fillMaxWidth().heightIn(min = 220.dp, max = 380.dp),
                    colors = TextFieldDefaults.outlinedTextFieldColors(
                        focusedBorderColor = EpPrimary, cursorColor = EpPrimary),
                )
                Spacer(Modifier.height(4.dp))
                Text("约 ${content.length} 字 · 保存后将重新分块并同步检索",
                    fontSize = 11.sp, color = TextSecondary)
            }
        },
        confirmButton = {
            Button(
                onClick = onSave, enabled = !busy,
                colors = ButtonDefaults.buttonColors(backgroundColor = EpPrimary),
            ) { Text(if (busy) "保存中…" else "保存", color = Color.White) }
        },
        dismissButton = { TextButton(onClick = onClose) { Text("取消") } },
    )
}

/** 知识库分类标签：科室库 = public 且带 department_code */
private fun kbTypeLabel(kb: JsonObject): Pair<String, Boolean> = when {
    kb["department_code"].str().isNotBlank() -> "科室" to true
    kb["type"].str() == "public" -> "公共" to true
    else -> "个人" to false
}

/** 当前知识库类型值（用于编辑弹窗的默认选中）：department / public / personal */
private fun kbTypeValue(kb: JsonObject): String = when {
    kb["department_code"].str().isNotBlank() -> "department"
    kb["type"].str() == "public" -> "public"
    else -> "personal"
}

/**
 * 知识库编辑弹窗（科室管理员 / 系统管理员）。
 * 可修改名称、描述与类型（个人 ↔ 科室 ↔ 公共）；
 * 类型的细粒度权限（谁能设公共、谁能设科室）由服务端按角色校验并返回明确提示。
 */
@Composable
private fun KbEditDialog(
    kb: JsonObject,
    onDismiss: () -> Unit,
    onSave: (name: String, desc: String, kbType: String) -> Unit,
) {
    var name by remember { mutableStateOf(kb["name"].str()) }
    var desc by remember { mutableStateOf(kb["description"].str()) }
    // 可选类型按角色给出：公共（系统管理员）/ 科室（科室管理员与系统管理员）/ 个人（均可）
    val typeOptions = buildList {
        if (AppState.isDeveloper) add("public" to "公共知识库（全员可见）")
        if (AppState.isKnowledgeAdmin || AppState.isDeveloper)
            add("department" to "科室知识库（本科室可见）")
        add("personal" to "个人知识库（仅自己可见）")
    }
    var kbType by remember { mutableStateOf(kbTypeValue(kb)) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("编辑知识库", fontWeight = FontWeight.SemiBold) },
        text = {
            Column {
                OutlinedTextField(value = name, onValueChange = { name = it },
                    label = { Text("名称") }, singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                    colors = TextFieldDefaults.outlinedTextFieldColors(
                        focusedBorderColor = EpPrimary, cursorColor = EpPrimary))
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(value = desc, onValueChange = { desc = it },
                    label = { Text("描述") }, modifier = Modifier.fillMaxWidth(),
                    colors = TextFieldDefaults.outlinedTextFieldColors(
                        focusedBorderColor = EpPrimary, cursorColor = EpPrimary))
                Spacer(Modifier.height(12.dp))
                Text("类型", fontSize = 13.sp, color = TextRegular)
                Spacer(Modifier.height(4.dp))
                typeOptions.forEach { (value, label) ->
                    Row(
                        Modifier.fillMaxWidth()
                            .clip(RoundedCornerShape(6.dp))
                            .clickable { kbType = value }
                            .padding(vertical = 2.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        RadioButton(
                            selected = kbType == value,
                            onClick = { kbType = value },
                            colors = RadioButtonDefaults.colors(selectedColor = EpPrimary),
                        )
                        Text(label, fontSize = 13.sp, color = TextPrimary)
                    }
                }
                Spacer(Modifier.height(4.dp))
                Text("改为科室/公共后，可见范围立即扩大；改为个人后仅创建者可见",
                    fontSize = 11.sp, color = TextSecondary)
            }
        },
        confirmButton = {
            Button(
                onClick = { if (name.isNotBlank()) onSave(name, desc, kbType) },
                colors = ButtonDefaults.buttonColors(backgroundColor = EpPrimary),
            ) { Text("保存", color = Color.White) }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } },
    )
}

@Composable
private fun KnowledgeList(vm: KnowledgeViewModel) {
    var search by remember { mutableStateOf("") }
    var showCreate by remember { mutableStateOf(false) }

    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        // 统计条：公共 / 科室 / 个人知识库数目 + 文档总数
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
                    Text("操作", Modifier.width(240.dp), fontSize = 13.sp, color = TextSecondary)
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
                            val (label, green) = kbTypeLabel(kb)
                            KbTag(label, green)
                        }
                        Text("${kb["doc_count"].int()}", Modifier.width(90.dp),
                            fontSize = 13.sp, color = EpSuccess)
                        Text(kb["created_at"].str().take(10), Modifier.width(160.dp),
                            fontSize = 13.sp, color = TextRegular)
                        Row(Modifier.width(240.dp)) {
                            TextButton(onClick = { vm.select(kb) }) {
                                Text("查看", color = EpPrimary, fontSize = 13.sp)
                            }
                            if (AppState.isAdmin) {
                                TextButton(onClick = { vm.editingKb = kb }) {
                                    Text("编辑", color = TextRegular, fontSize = 13.sp)
                                }
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
        // 可选类型按角色给出：公共（系统管理员）/ 科室（科室管理员）/ 个人（所有人）
        val typeOptions = buildList {
            if (AppState.isDeveloper) add("public" to "公共知识库（全员可见）")
            if (AppState.isKnowledgeAdmin || AppState.isDeveloper)
                add("department" to "科室知识库（本科室可见）")
            add("personal" to "个人知识库（仅自己可见）")
        }
        var kbType by remember { mutableStateOf(typeOptions.last().first) }
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
                    Spacer(Modifier.height(12.dp))
                    Text("类型", fontSize = 13.sp, color = TextRegular)
                    Spacer(Modifier.height(4.dp))
                    typeOptions.forEach { (value, label) ->
                        Row(
                            Modifier.fillMaxWidth()
                                .clip(RoundedCornerShape(6.dp))
                                .clickable { kbType = value }
                                .padding(vertical = 2.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            RadioButton(
                                selected = kbType == value,
                                onClick = { kbType = value },
                                colors = RadioButtonDefaults.colors(selectedColor = EpPrimary),
                            )
                            Text(label, fontSize = 13.sp, color = TextPrimary)
                        }
                    }
                }
            },
            confirmButton = {
                Button(onClick = {
                    if (name.isNotBlank()) { vm.create(name, desc, kbType); showCreate = false }
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
            val (label, green) = kbTypeLabel(kb)
            KbTag(label, green)
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
                    Text("操作", Modifier.width(170.dp), fontSize = 13.sp, color = TextSecondary)
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
                            .clip(RoundedCornerShape(4.dp))
                            .clickable { vm.openDocument(d["id"].str()) }
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
                            Row(Modifier.width(170.dp)) {
                                TextButton(onClick = { vm.openDocument(d["id"].str()) }) {
                                    Text("查看/编辑", color = EpPrimary, fontSize = 13.sp)
                                }
                                TextButton(onClick = { vm.deleteDocument(d["id"].str()) }) {
                                    Icon(Icons.Default.Delete, null, tint = EpDanger,
                                        modifier = Modifier.size(16.dp))
                                }
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
