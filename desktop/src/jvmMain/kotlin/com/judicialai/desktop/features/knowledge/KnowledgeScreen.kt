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
import androidx.compose.foundation.text.selection.SelectionContainer
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
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.core.platform.pickFiles
import com.judicialai.desktop.core.utils.int
import com.judicialai.desktop.core.utils.str
import com.judicialai.desktop.data.Repositories
import com.judicialai.desktop.design.components.AppButton
import com.judicialai.desktop.design.components.AppButtonKind
import com.judicialai.desktop.design.components.AppDialog
import com.judicialai.desktop.design.components.MarkdownView
import com.judicialai.desktop.design.theme.Dimens
import com.judicialai.desktop.design.theme.EpDanger
import com.judicialai.desktop.design.theme.EpPrimary
import com.judicialai.desktop.design.theme.EpSuccess
import com.judicialai.desktop.design.theme.Ink
import com.judicialai.desktop.design.theme.Line
import com.judicialai.desktop.design.theme.SurfaceTonal
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
            editable = vm.currentKb?.let(::canWriteKb) ?: false,
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
 *
 * 使用统一 [AppDialog]：内容区可滚动、弹窗高度受限（maxHeight），
 * 不再使用 M2 AlertDialog（其 baseline 排版会导致多行输入框滚动时弹窗被撑高、
 * 标题与正文之间出现空白）。
 */
@Composable
fun KnowledgeDocDialog(
    title: String,
    content: String,
    busy: Boolean,
    editable: Boolean = true,
    onTitleChange: (String) -> Unit,
    onContentChange: (String) -> Unit,
    onSave: () -> Unit,
    onClose: () -> Unit,
) {
    AppDialog(
        onDismissRequest = onClose,
        title = if (editable) "查看 / 编辑文档" else "查看文档",
        width = 640.dp,
        actions = {
            AppButton("关闭", onClick = onClose, kind = AppButtonKind.SECONDARY)
            if (editable) {
                Spacer(Modifier.width(Dimens.space2))
                AppButton(if (busy) "保存中…" else "保存修改", onClick = onSave, enabled = !busy)
            }
        },
    ) {
        OutlinedTextField(
            value = title, onValueChange = onTitleChange,
            label = { Text("标题", fontSize = 13.sp) }, singleLine = true,
            enabled = editable,
            modifier = Modifier.fillMaxWidth(),
            textStyle = TextStyle(fontSize = 14.sp, color = Ink),
            shape = RoundedCornerShape(Dimens.radiusControl),
            colors = docFieldColors(),
        )
        if (editable) {
            OutlinedTextField(
                value = content, onValueChange = onContentChange,
                label = { Text("正文内容", fontSize = 13.sp) },
                placeholder = {
                    Text(if (busy) "正在加载正文…" else "（该文档暂无正文内容）",
                        fontSize = 13.sp, color = TextPlaceholder)
                },
                modifier = Modifier.fillMaxWidth().height(DocContentFieldHeight),
                textStyle = TextStyle(fontSize = 14.sp, color = Ink, lineHeight = 22.sp),
                shape = RoundedCornerShape(Dimens.radiusControl),
                colors = docFieldColors(),
            )
        } else {
            SelectionContainer {
                Column(
                    Modifier.fillMaxWidth().height(DocContentFieldHeight)
                        .verticalScroll(rememberScrollState())
                        .clip(RoundedCornerShape(Dimens.radiusControl))
                        .background(SurfaceTonal)
                        .padding(14.dp),
                ) {
                    if (busy) {
                        Text("正在加载正文…", fontSize = 13.sp, color = TextPlaceholder)
                    } else {
                        MarkdownView(content.ifBlank { "（该文档暂无正文内容）" })
                    }
                }
            }
        }
        Text(
            if (editable) "约 ${content.length} 字 · 保存后将重新分块并同步检索"
            else "约 ${content.length} 字 · 当前知识库为只读",
            fontSize = 11.sp, color = TextSecondary)
    }
}

/** 正文框固定高度：够放下十几行正文，同时保证弹窗总高不超过普通窗口的可视高度 */
private val DocContentFieldHeight = 300.dp

/**
 * 文档弹窗内两个输入框统一的配色：tonal 底 + 标准描边。
 * 不用 outlinedTextFieldColors() 的默认值（backgroundColor 透明、边框是 onSurface 的
 * 低透明度灰），否则输入框与白色弹窗底同色、滚动时看不出边界。
 */
@Composable
private fun docFieldColors() = TextFieldDefaults.outlinedTextFieldColors(
    textColor = Ink,
    backgroundColor = SurfaceTonal,
    cursorColor = EpPrimary,
    focusedBorderColor = EpPrimary,
    unfocusedBorderColor = Line,
    focusedLabelColor = EpPrimary,
    unfocusedLabelColor = TextRegular,
    placeholderColor = TextPlaceholder,
)

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

/** 客户端只展示真实可执行的维护动作；服务端仍负责最终权限校验。 */
private fun canWriteKb(kb: JsonObject): Boolean = when (kbTypeValue(kb)) {
    "public" -> AppState.isDeveloper
    "department" -> AppState.isKnowledgeAdmin || AppState.isDeveloper
    else -> true
}

/** 按角色可选的知识库类型选项：公共（系统管理员）/ 科室（科室管理员与系统管理员）/ 个人（均可） */
private fun kbTypeOptions(): List<Pair<String, String>> = buildList {
    if (AppState.isDeveloper) add("public" to "公共知识库（全员可见）")
    if (AppState.isKnowledgeAdmin || AppState.isDeveloper)
        add("department" to "科室知识库（本科室可见）")
    add("personal" to "个人知识库（仅自己可见）")
}

/** 知识库类型单选列表（编辑 / 新建弹窗共用） */
@Composable
private fun KbTypeSelector(kbType: String, onSelect: (String) -> Unit) {
    Text("类型", fontSize = 13.sp, color = TextRegular)
    kbTypeOptions().forEach { (value, label) ->
        Row(
            Modifier.fillMaxWidth()
                .clip(RoundedCornerShape(6.dp))
                .clickable { onSelect(value) }
                .padding(vertical = 2.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            RadioButton(
                selected = kbType == value,
                onClick = { onSelect(value) },
                colors = RadioButtonDefaults.colors(selectedColor = EpPrimary),
            )
            Text(label, fontSize = 13.sp, color = TextPrimary)
        }
    }
}

/**
 * 知识库编辑弹窗（科室管理员 / 系统管理员）。
 * 可修改名称、描述与类型（个人 ↔ 科室 ↔ 公共）；
 * 类型的细粒度权限（谁能设公共、谁能设科室）由服务端按角色校验并返回明确提示。
 * 使用统一 [AppDialog]（内容区可滚动、限高），避免溢出。
 */
@Composable
private fun KbEditDialog(
    kb: JsonObject,
    onDismiss: () -> Unit,
    onSave: (name: String, desc: String, kbType: String) -> Unit,
) {
    var name by remember { mutableStateOf(kb["name"].str()) }
    var desc by remember { mutableStateOf(kb["description"].str()) }
    var kbType by remember { mutableStateOf(kbTypeValue(kb)) }

    AppDialog(
        onDismissRequest = onDismiss,
        title = "编辑知识库",
        width = 520.dp,
        actions = {
            AppButton("取消", onClick = onDismiss, kind = AppButtonKind.SECONDARY)
            Spacer(Modifier.width(Dimens.space2))
            AppButton("保存", onClick = { if (name.isNotBlank()) onSave(name, desc, kbType) },
                enabled = name.isNotBlank())
        },
    ) {
        OutlinedTextField(value = name, onValueChange = { name = it },
            label = { Text("名称") }, singleLine = true,
            modifier = Modifier.fillMaxWidth(),
            colors = TextFieldDefaults.outlinedTextFieldColors(
                focusedBorderColor = EpPrimary, cursorColor = EpPrimary))
        OutlinedTextField(value = desc, onValueChange = { desc = it },
            label = { Text("描述") }, modifier = Modifier.fillMaxWidth(),
            colors = TextFieldDefaults.outlinedTextFieldColors(
                focusedBorderColor = EpPrimary, cursorColor = EpPrimary))
        KbTypeSelector(kbType) { kbType = it }
        Text("改为科室/公共后，可见范围立即扩大；改为个人后仅创建者可见",
            fontSize = 11.sp, color = TextSecondary)
    }
}

@Composable
private fun KnowledgeList(vm: KnowledgeViewModel) {
    var search by remember { mutableStateOf("") }
    var showCreate by remember { mutableStateOf(false) }
    var pendingDeleteKb by remember { mutableStateOf<JsonObject?>(null) }

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
                    modifier = Modifier.width(220.dp).heightIn(min = 56.dp),
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
                            if (canWriteKb(kb)) {
                                TextButton(onClick = { vm.editingKb = kb }) {
                                    Text("编辑", color = TextRegular, fontSize = 13.sp)
                                }
                                TextButton(onClick = { pendingDeleteKb = kb }) {
                                    Text("删除", color = EpDanger, fontSize = 13.sp)
                                }
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
        var kbType by remember { mutableStateOf(kbTypeOptions().last().first) }
        AppDialog(
            onDismissRequest = { showCreate = false },
            title = "新建知识库",
            width = 520.dp,
            actions = {
                AppButton("取消", onClick = { showCreate = false }, kind = AppButtonKind.SECONDARY)
                Spacer(Modifier.width(Dimens.space2))
                AppButton("创建", onClick = {
                    if (name.isNotBlank()) { vm.create(name, desc, kbType); showCreate = false }
                }, enabled = name.isNotBlank())
            },
        ) {
            OutlinedTextField(value = name, onValueChange = { name = it },
                label = { Text("名称") }, singleLine = true,
                modifier = Modifier.fillMaxWidth(),
                colors = TextFieldDefaults.outlinedTextFieldColors(
                    focusedBorderColor = EpPrimary, cursorColor = EpPrimary))
            OutlinedTextField(value = desc, onValueChange = { desc = it },
                label = { Text("描述") }, modifier = Modifier.fillMaxWidth(),
                colors = TextFieldDefaults.outlinedTextFieldColors(
                    focusedBorderColor = EpPrimary, cursorColor = EpPrimary))
            KbTypeSelector(kbType) { kbType = it }
        }
    }

    pendingDeleteKb?.let { kb ->
        AppDialog(
            onDismissRequest = { pendingDeleteKb = null },
            title = "删除知识库",
            subtitle = "删除后该知识库将不再用于检索，关联内容可能无法恢复。",
            width = 480.dp,
            actions = {
                AppButton("取消", onClick = { pendingDeleteKb = null }, kind = AppButtonKind.SECONDARY)
                Spacer(Modifier.width(Dimens.space2))
                AppButton("确认删除", onClick = {
                    vm.deleteKb(kb["id"].str())
                    pendingDeleteKb = null
                }, kind = AppButtonKind.DANGER)
            },
        ) {
            Text("知识库：${kb["name"].str().ifBlank { "未命名知识库" }}",
                fontSize = 13.sp, color = TextPrimary)
            Text("当前含 ${kb["doc_count"].int()} 篇文档",
                fontSize = 12.sp, color = TextSecondary)
        }
    }
}

/** 知识库详情：对应 Web KnowledgeDetailView（返回头 + 文档表格 + 上传 + 库内搜索） */
@Composable
private fun KnowledgeDetail(vm: KnowledgeViewModel) {
    val kb = vm.currentKb ?: return
    val writable = canWriteKb(kb)
    var pendingDeleteDoc by remember { mutableStateOf<JsonObject?>(null) }
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
            if (writable) {
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
            } else {
                Text("只读", fontSize = 12.sp, color = TextSecondary)
            }
        }

        // 库内搜索：即输即搜，服务端一次返回全部结果（标题命中排前、内容命中排后），
        // 响应到达立刻替换列表，不存在「等全部查完才显示」
        OutlinedTextField(
            value = vm.searchQuery,
            onValueChange = { vm.search(it) },
            placeholder = { Text("搜索本库文档：先列标题命中的，再列内容命中的", fontSize = 13.sp) },
            leadingIcon = { Icon(Icons.Default.Search, null, tint = TextSecondary) },
            trailingIcon = {
                if (vm.searchQuery.isNotBlank()) {
                    TextButton(onClick = { vm.clearSearch() }) {
                        Text("清空", fontSize = 12.sp, color = TextSecondary)
                    }
                }
            },
            singleLine = true,
            modifier = Modifier.fillMaxWidth().heightIn(min = 56.dp),
            colors = TextFieldDefaults.outlinedTextFieldColors(
                focusedBorderColor = EpPrimary, cursorColor = EpPrimary),
        )

        if (vm.searchResults == null) {
            Row(
                Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text("排序：", fontSize = 12.sp, color = TextSecondary)
                listOf(
                    "newest" to "最新上传",
                    "oldest" to "最早上传",
                    "title" to "标题",
                ).forEach { (key, labelText) ->
                    val selected = vm.docSort == key
                    TextButton(onClick = { vm.changeDocSort(key) }) {
                        Text(
                            labelText,
                            fontSize = 12.sp,
                            color = if (selected) EpPrimary else TextRegular,
                            fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
                        )
                    }
                }
                Spacer(Modifier.weight(1f))
                val pageCount = ((vm.docTotal + vm.docPageSize - 1) / vm.docPageSize)
                    .coerceAtLeast(1)
                Text("共 " + vm.docTotal + " 篇 · 第 " + vm.docPage + "/" + pageCount + " 页",
                    fontSize = 12.sp, color = TextSecondary)
                TextButton(
                    onClick = { vm.prevDocPage() },
                    enabled = vm.docPage > 1,
                ) { Text("上一页", fontSize = 12.sp) }
                TextButton(
                    onClick = { vm.nextDocPage() },
                    enabled = vm.docPage * vm.docPageSize < vm.docTotal,
                ) { Text("下一页", fontSize = 12.sp) }
            }
        }
        Card(shape = RoundedCornerShape(8.dp), elevation = 0.dp,
            modifier = Modifier.fillMaxWidth().weight(1f)) {
            val results = vm.searchResults
            if (results != null) {
                SearchResultList(vm, results, writable) { pendingDeleteDoc = it }
            } else {
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
                            DocRow(vm, d, snippet = null, writable = writable,
                                onDeleteRequest = { pendingDeleteDoc = it })
                            Divider(color = Color(0xFFF2F4F8))
                        }
                    }
                }
            }
        }
        vm.status?.let { Text(it, fontSize = 12.sp, color = TextSecondary) }
    }

    pendingDeleteDoc?.let { doc ->
        AppDialog(
            onDismissRequest = { pendingDeleteDoc = null },
            title = "删除知识库文档",
            subtitle = "删除后该文档将退出知识检索范围。",
            width = 460.dp,
            actions = {
                AppButton("取消", onClick = { pendingDeleteDoc = null }, kind = AppButtonKind.SECONDARY)
                Spacer(Modifier.width(Dimens.space2))
                AppButton("确认删除", onClick = {
                    vm.deleteDocument(doc["id"].str())
                    pendingDeleteDoc = null
                }, kind = AppButtonKind.DANGER)
            },
        ) {
            Text(doc["title"].str().ifBlank { doc["filename"].str().ifBlank { "未命名文档" } },
                fontSize = 13.sp, color = TextPrimary)
        }
    }
}

/** 搜索结果：标题命中一组在前，内容命中一组在后（带命中片段），点击即打开全文 */
@Composable
private fun SearchResultList(
    vm: KnowledgeViewModel,
    results: List<JsonObject>,
    writable: Boolean,
    onDeleteRequest: (JsonObject) -> Unit,
) {
    val titleHits = results.filter { it["match"].str() != "content" }
    val contentHits = results.filter { it["match"].str() == "content" }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
        Row(Modifier.fillMaxWidth().background(Color(0xFFFAFAFA))
            .padding(horizontal = 20.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically) {
            Text(
                if (vm.searching) "正在搜索「${vm.searchQuery}」…"
                else "「${vm.searchQuery}」共 ${results.size} 条结果",
                fontSize = 12.5.sp, color = TextSecondary)
        }
        if (results.isEmpty() && !vm.searching) {
            Box(Modifier.fillMaxWidth().padding(40.dp), contentAlignment = Alignment.Center) {
                Text("没有找到匹配的文档", color = TextSecondary, fontSize = 13.sp)
            }
        }
        if (titleHits.isNotEmpty()) {
            SearchGroupHeader("标题命中（${titleHits.size}）")
            titleHits.forEach { d ->
                DocRow(vm, d, snippet = null, writable = writable, onDeleteRequest = onDeleteRequest)
                Divider(color = Color(0xFFF2F4F8))
            }
        }
        if (contentHits.isNotEmpty()) {
            SearchGroupHeader("内容命中（${contentHits.size}）")
            contentHits.forEach { d ->
                DocRow(vm, d, snippet = d["snippet"].str().ifBlank { null },
                    writable = writable, onDeleteRequest = onDeleteRequest)
                Divider(color = Color(0xFFF2F4F8))
            }
        }
    }
}

@Composable
private fun SearchGroupHeader(text: String) {
    Text(text, fontSize = 12.sp, color = EpPrimary, fontWeight = FontWeight.Medium,
        modifier = Modifier.fillMaxWidth()
            .background(EpPrimary.copy(alpha = 0.06f))
            .padding(horizontal = 20.dp, vertical = 6.dp))
}

/** 文档行（普通列表与搜索结果共用）：标题 / 类型 / 状态 / 时间 / 操作；搜索内容命中时多一行命中片段 */
@Composable
private fun DocRow(
    vm: KnowledgeViewModel,
    d: JsonObject,
    snippet: String?,
    writable: Boolean,
    onDeleteRequest: (JsonObject) -> Unit,
) {
    Row(Modifier.fillMaxWidth()
        .clip(RoundedCornerShape(4.dp))
        .clickable { vm.openDocument(d["id"].str()) }
        .padding(horizontal = 20.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(2f)) {
            Text(d["title"].str().ifBlank { d["filename"].str() },
                fontSize = 14.sp, color = TextPrimary,
                maxLines = 1, overflow = TextOverflow.Ellipsis)
            if (snippet != null) {
                Spacer(Modifier.height(3.dp))
                Text("…$snippet…", fontSize = 12.sp, color = TextSecondary,
                    maxLines = 2, overflow = TextOverflow.Ellipsis)
            }
        }
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
                Text(if (writable) "查看/编辑" else "查看", color = EpPrimary, fontSize = 13.sp)
            }
            if (writable) {
                TextButton(onClick = { onDeleteRequest(d) }) {
                    Icon(Icons.Default.Delete, null, tint = EpDanger,
                        modifier = Modifier.size(16.dp))
                }
            }
        }
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
