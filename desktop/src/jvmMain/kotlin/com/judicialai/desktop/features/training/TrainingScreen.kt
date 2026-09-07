package com.judicialai.desktop.features.training

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.AlertDialog
import androidx.compose.material.Button
import androidx.compose.material.ButtonDefaults
import androidx.compose.material.Card
import androidx.compose.material.Checkbox
import androidx.compose.material.Divider
import androidx.compose.material.Icon
import androidx.compose.material.OutlinedTextField
import androidx.compose.material.Text
import androidx.compose.material.TextButton
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.core.platform.pickFiles
import com.judicialai.desktop.core.utils.int
import com.judicialai.desktop.core.utils.obj
import com.judicialai.desktop.core.utils.str
import com.judicialai.desktop.data.Repositories
import com.judicialai.desktop.design.theme.EpDanger
import com.judicialai.desktop.design.theme.EpPrimary
import com.judicialai.desktop.design.theme.EpSuccess
import com.judicialai.desktop.design.theme.EpWarning
import com.judicialai.desktop.design.theme.TextPlaceholder
import com.judicialai.desktop.design.theme.TextSecondary
import kotlinx.serialization.json.JsonObject

private val TABS = listOf("数据资产", "样本审核", "数据集", "训练任务", "模型版本")

private val SOURCE_NAMES = mapOf(
    "business" to "业务过程", "historical" to "历史公文", "batch" to "批量导入",
    "excel" to "Excel导入", "jsonl" to "JSONL导入", "chat" to "业务真实数据",
    "ai_generated" to "AI辅助生成", "import" to "批量导入",
)
private val STATUS_NAMES = mapOf(
    "candidate" to "待审核", "approved" to "已通过", "disabled" to "已禁用",
    "pending" to "排队中", "running" to "训练中", "succeeded" to "已完成",
    "failed" to "失败", "canceled" to "已取消",
    "Training" to "训练中", "Ready" to "就绪", "Published" to "已发布",
    "Archived" to "已归档", "Failed" to "失败",
)

private fun statusColor(s: String): Color = when (s) {
    "approved", "succeeded", "Ready", "Published" -> EpSuccess
    "candidate", "pending", "running", "Training" -> EpWarning
    "failed", "Failed", "disabled" -> EpDanger
    else -> TextSecondary
}

/** 数据资产中心：数据资产 → 审核 → 数据集 → 训练 → 模型版本 */
@Composable
fun TrainingScreen() {
    val vm = remember { TrainingViewModel(Repositories.training) }
    var tab by remember { mutableStateOf(0) }
    LaunchedEffect(Unit) { vm.loadOverview(); vm.loadAssets(); vm.loadSamples(); vm.loadDatasets(); vm.loadJobs(); vm.loadModels() }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)) {

        // 统计条
        Row(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
            vm.overview.forEach { (label, value) ->
                Card(Modifier.weight(1f), shape = RoundedCornerShape(8.dp), elevation = 0.dp) {
                    Column(Modifier.fillMaxWidth().padding(14.dp),
                        horizontalAlignment = Alignment.CenterHorizontally) {
                        Text(value, fontSize = 24.sp, fontWeight = FontWeight.Bold, color = EpPrimary)
                        Spacer(Modifier.height(6.dp))
                        Text(label, fontSize = 12.sp, color = TextSecondary)
                    }
                }
            }
        }

        // 页签
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            TABS.forEachIndexed { i, name ->
                val active = tab == i
                Text(name, fontSize = 14.sp,
                    color = if (active) Color.White else TextSecondary,
                    modifier = Modifier
                        .background(if (active) EpPrimary else Color(0xFFF0F2F5), RoundedCornerShape(6.dp))
                        .clickable { tab = i }
                        .padding(horizontal = 16.dp, vertical = 8.dp))
            }
            Spacer(Modifier.weight(1f))
            vm.status?.let { Text(it, fontSize = 12.sp, color = TextSecondary) }
        }

        when (tab) {
            0 -> AssetTab(vm)
            1 -> SampleTab(vm)
            2 -> DatasetTab(vm)
            3 -> JobTab(vm)
            4 -> ModelTab(vm)
        }
    }
}

// ==================== 数据资产 ====================

@Composable
private fun AssetTab(vm: TrainingViewModel) {
    var showImportDir by remember { mutableStateOf(false) }

    Card(shape = RoundedCornerShape(8.dp), elevation = 0.dp) {
        Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            OutlinedTextField(
                value = vm.assetKeyword, onValueChange = { vm.assetKeyword = it },
                placeholder = { Text("搜索标题 / 文件名", fontSize = 13.sp) },
                singleLine = true, modifier = Modifier.width(220.dp).height(50.dp))
            SourceFilter(vm.assetSourceFilter) { vm.assetSourceFilter = it }
            TextButton(onClick = { vm.loadAssets(1) }) { Text("查询", color = EpPrimary) }
            Spacer(Modifier.weight(1f))
            OutlinedButton(text = "导入外部目录") { showImportDir = true }
            Button(onClick = {
                pickFiles("选择文件（ZIP / Excel / JSONL / 单个公文）").firstOrNull()?.let { vm.importFile(it) }
            }, colors = ButtonDefaults.buttonColors(backgroundColor = EpPrimary), enabled = !vm.busy) {
                Icon(Icons.Default.Add, null, tint = Color.White)
                Spacer(Modifier.width(4.dp)); Text("导入文件", color = Color.White)
            }
        }
    }

    Card(shape = RoundedCornerShape(8.dp), elevation = 0.dp) {
        Column(Modifier.padding(12.dp)) {
            vm.assets.forEach { a ->
                Row(Modifier.fillMaxWidth().padding(vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Column(Modifier.weight(1f)) {
                        Text(a["title"].str().ifBlank { a["name"].str() },
                            fontSize = 14.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text("${SOURCE_NAMES[a["source_type"].str()] ?: a["source_type"].str()} · " +
                            "${a["doc_type"].str().ifBlank { "未识别文种" }} · ${a["char_count"].int()} 字",
                            fontSize = 12.sp, color = TextSecondary)
                    }
                    if (a["sample_generated"].int() == 0) {
                        TextButton(onClick = { vm.generateSample(a["id"].str()) }, enabled = !vm.busy) {
                            Text("生成训练样本", fontSize = 12.sp, color = EpPrimary)
                        }
                    } else {
                        Text("已生成样本", fontSize = 12.sp, color = EpSuccess)
                    }
                    TextButton(onClick = { vm.deleteAsset(a["id"].str()) }) {
                        Text("删除", fontSize = 12.sp, color = EpDanger)
                    }
                }
                Divider()
            }
            if (vm.assets.isEmpty()) {
                Text("暂无数据资产，请通过右上角导入", Modifier.padding(20.dp),
                    fontSize = 13.sp, color = TextPlaceholder)
            }
            Pager(vm.assetTotal, vm.assetPage) { vm.loadAssets(it) }
        }
    }

    if (showImportDir) {
        var path by remember { mutableStateOf("") }
        var sourceType by remember { mutableStateOf("historical") }
        AlertDialog(
            onDismissRequest = { showImportDir = false },
            title = { Text("批量导入历史公文") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text("直接指定服务器上的外部目录（如 /data/judicial_documents），系统会自动扫描、提取正文、识别标题与文种，不复制原始文件。",
                        fontSize = 12.sp, color = TextSecondary)
                    OutlinedTextField(value = path, onValueChange = { path = it },
                        label = { Text("外部目录路径") }, singleLine = true,
                        modifier = Modifier.fillMaxWidth())
                    SourceFilter(sourceType) { sourceType = it }
                }
            },
            confirmButton = {
                Button(onClick = { vm.importDir(path, sourceType); showImportDir = false },
                    colors = ButtonDefaults.buttonColors(backgroundColor = EpPrimary)) {
                    Text("开始导入", color = Color.White)
                }
            },
            dismissButton = { TextButton(onClick = { showImportDir = false }) { Text("取消") } },
        )
    }
}

@Composable
private fun SourceFilter(value: String, onChange: (String) -> Unit) {
    var expanded by remember { mutableStateOf(false) }
    Column {
        Text(SOURCE_NAMES[value] ?: "全部来源", fontSize = 13.sp,
            modifier = Modifier.background(Color(0xFFF0F2F5), RoundedCornerShape(6.dp))
                .clickable { expanded = true }.padding(horizontal = 12.dp, vertical = 10.dp))
        if (expanded) {
            Card(elevation = 4.dp) {
                Column {
                    listOf("" to "全部来源", "business" to "业务过程", "historical" to "历史公文",
                        "batch" to "批量导入", "excel" to "Excel导入").forEach { (k, v) ->
                        Text(v, fontSize = 13.sp,
                            modifier = Modifier.clickable { onChange(k); expanded = false }
                                .padding(horizontal = 16.dp, vertical = 8.dp))
                    }
                }
            }
        }
    }
}

// ==================== 样本审核 ====================

@Composable
private fun SampleTab(vm: TrainingViewModel) {
    var editing by remember { mutableStateOf<JsonObject?>(null) }

    Card(shape = RoundedCornerShape(8.dp), elevation = 0.dp) {
        Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf("candidate", "approved", "disabled", "").forEach { s ->
                val label = if (s.isEmpty()) "全部" else STATUS_NAMES[s]!!
                val count = if (s.isEmpty()) vm.sampleCounts.values.sum() else vm.sampleCounts[s] ?: 0
                val active = vm.sampleStatusFilter == s
                Text("$label($count)", fontSize = 13.sp,
                    color = if (active) Color.White else TextSecondary,
                    modifier = Modifier.background(
                        if (active) EpPrimary else Color(0xFFF0F2F5), RoundedCornerShape(6.dp))
                        .clickable { vm.sampleStatusFilter = s; vm.loadSamples(1) }
                        .padding(horizontal = 12.dp, vertical = 7.dp))
            }
            Spacer(Modifier.weight(1f))
            Text("只有通过审核的数据才能进入训练集", fontSize = 12.sp, color = TextPlaceholder)
        }
    }

    Card(shape = RoundedCornerShape(8.dp), elevation = 0.dp) {
        Column(Modifier.padding(12.dp)) {
            vm.samples.forEach { s ->
                Column(Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text(STATUS_NAMES[s["status"].str()] ?: s["status"].str(),
                            fontSize = 11.sp, color = statusColor(s["status"].str()))
                        Text(SOURCE_NAMES[s["source"].str()] ?: s["source"].str(),
                            fontSize = 11.sp, color = TextSecondary)
                        if (s["biz_type"].str().isNotBlank())
                            Text(s["biz_type"].str(), fontSize = 11.sp, color = TextSecondary)
                        Spacer(Modifier.weight(1f))
                        TextButton(onClick = { editing = s }) { Text("编辑", fontSize = 12.sp) }
                        if (s["status"].str() != "approved")
                            TextButton(onClick = { vm.reviewSample(s["id"].str(), "approve") }) {
                                Text("通过", fontSize = 12.sp, color = EpSuccess)
                            }
                        if (s["status"].str() != "disabled")
                            TextButton(onClick = { vm.reviewSample(s["id"].str(), "disable") }) {
                                Text("禁用", fontSize = 12.sp, color = EpWarning)
                            }
                        TextButton(onClick = { vm.deleteSample(s["id"].str()) }) {
                            Text("删除", fontSize = 12.sp, color = EpDanger)
                        }
                    }
                    Text("需求：${s["instruction"].str()}", fontSize = 13.sp,
                        maxLines = 2, overflow = TextOverflow.Ellipsis)
                    Text("成稿：${s["output"].str().take(120)}…", fontSize = 12.sp,
                        color = TextSecondary, maxLines = 2, overflow = TextOverflow.Ellipsis)
                }
                Divider()
            }
            if (vm.samples.isEmpty())
                Text("暂无样本。可在「数据资产」页生成候选样本，或在写作对话中点击「加入训练集」。",
                    Modifier.padding(20.dp), fontSize = 13.sp, color = TextPlaceholder)
            Pager(vm.sampleTotal, vm.samplePage) { vm.loadSamples(it) }
        }
    }

    editing?.let { s ->
        var ins by remember { mutableStateOf(s["instruction"].str()) }
        var inp by remember { mutableStateOf(s["input"].str()) }
        var out by remember { mutableStateOf(s["output"].str()) }
        AlertDialog(
            onDismissRequest = { editing = null },
            title = { Text("编辑训练样本") },
            text = {
                Column(Modifier.fillMaxWidth().heightIn(max = 480.dp)
                    .verticalScroll(rememberScrollState()),
                    verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(ins, { ins = it }, label = { Text("写作需求") },
                        modifier = Modifier.fillMaxWidth())
                    OutlinedTextField(inp, { inp = it }, label = { Text("背景信息（可选）") },
                        modifier = Modifier.fillMaxWidth())
                    OutlinedTextField(out, { out = it }, label = { Text("最终成稿") },
                        modifier = Modifier.fillMaxWidth().height(220.dp))
                }
            },
            confirmButton = {
                Button(onClick = {
                    vm.editSample(s["id"].str(), ins, inp, out); editing = null
                }, colors = ButtonDefaults.buttonColors(backgroundColor = EpPrimary)) {
                    Text("保存", color = Color.White)
                }
            },
            dismissButton = { TextButton(onClick = { editing = null }) { Text("取消") } },
        )
    }
}

// ==================== 数据集 ====================

@Composable
private fun DatasetTab(vm: TrainingViewModel) {
    var showCreate by remember { mutableStateOf(false) }
    var versionFor by remember { mutableStateOf<String?>(null) }

    Card(shape = RoundedCornerShape(8.dp), elevation = 0.dp) {
        Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("数据集与版本：每次生成版本会自动进行质量检查（去重 / 空文本 / 异常长度 / 缺失字段）",
                fontSize = 12.sp, color = TextSecondary)
            Spacer(Modifier.weight(1f))
            Button(onClick = { showCreate = true },
                colors = ButtonDefaults.buttonColors(backgroundColor = EpPrimary)) {
                Text("新建数据集", color = Color.White)
            }
        }
    }

    vm.datasets.forEach { d ->
        Card(shape = RoundedCornerShape(8.dp), elevation = 0.dp) {
            Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(d["name"].str(), fontSize = 15.sp, fontWeight = FontWeight.Medium)
                    Spacer(Modifier.weight(1f))
                    TextButton(onClick = { versionFor = d["id"].str() }, enabled = !vm.busy) {
                        Text("生成新版本", color = EpPrimary)
                    }
                }
                if (d["description"].str().isNotBlank())
                    Text(d["description"].str(), fontSize = 12.sp, color = TextSecondary)
                d["versions"].let { v -> kotlinx.serialization.json.JsonArray(
                    (v as? kotlinx.serialization.json.JsonArray)?.toList() ?: emptyList()) }
                    .forEach { ve ->
                        val ver = ve.obj() ?: return@forEach
                        val stats = ver["stats"].obj()
                        val check = ver["check_report"].obj()
                        Row(Modifier.fillMaxWidth()
                            .background(Color(0xFFF7F9FC), RoundedCornerShape(6.dp)).padding(10.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                            Text(ver["version"].str(), fontWeight = FontWeight.Medium)
                            Text("可训练 ${ver["sample_count"].int()} 条", fontSize = 12.sp)
                            val bySource = stats?.get("by_source")?.obj()
                            if (bySource != null) {
                                Text(bySource.entries.joinToString("  ") {
                                    "${SOURCE_NAMES[it.key] ?: it.key}:${it.value.int()}"
                                }, fontSize = 12.sp, color = TextSecondary,
                                    maxLines = 1, overflow = TextOverflow.Ellipsis,
                                    modifier = Modifier.weight(1f))
                            } else Spacer(Modifier.weight(1f))
                            if (check != null)
                                Text("检查：重复${check["duplicate"].int()} 缺失${check["missing"].int()} 异常${(check["abnormal"].int() + check["empty"].int())}",
                                    fontSize = 11.sp, color = TextSecondary)
                        }
                    }
                if ((d["versions"] as? kotlinx.serialization.json.JsonArray)?.isNotEmpty() != true)
                    Text("还没有版本，点击右上角「生成新版本」", fontSize = 12.sp, color = TextPlaceholder)
            }
        }
    }

    if (showCreate) {
        var name by remember { mutableStateOf("司法公文训练集") }
        var desc by remember { mutableStateOf("") }
        AlertDialog(
            onDismissRequest = { showCreate = false },
            title = { Text("新建数据集") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(name, { name = it }, label = { Text("名称") },
                        singleLine = true, modifier = Modifier.fillMaxWidth())
                    OutlinedTextField(desc, { desc = it }, label = { Text("说明（可选）") },
                        modifier = Modifier.fillMaxWidth())
                }
            },
            confirmButton = {
                Button(onClick = { vm.createDataset(name, desc); showCreate = false },
                    colors = ButtonDefaults.buttonColors(backgroundColor = EpPrimary)) {
                    Text("创建", color = Color.White)
                }
            },
            dismissButton = { TextButton(onClick = { showCreate = false }) { Text("取消") } },
        )
    }

    versionFor?.let { dsId ->
        var ver by remember { mutableStateOf("v1.0") }
        AlertDialog(
            onDismissRequest = { versionFor = null },
            title = { Text("生成数据集版本") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("将把当前全部「已通过」样本进行质量检查后固化为一个版本。",
                        fontSize = 12.sp, color = TextSecondary)
                    OutlinedTextField(ver, { ver = it }, label = { Text("版本号（如 v1.0）") },
                        singleLine = true, modifier = Modifier.fillMaxWidth())
                }
            },
            confirmButton = {
                Button(onClick = { vm.createVersion(dsId, ver); versionFor = null },
                    colors = ButtonDefaults.buttonColors(backgroundColor = EpPrimary),
                    enabled = !vm.busy) { Text("生成", color = Color.White) }
            },
            dismissButton = { TextButton(onClick = { versionFor = null }) { Text("取消") } },
        )
    }
}

// ==================== 训练任务 ====================

@Composable
private fun JobTab(vm: TrainingViewModel) {
    var showCreate by remember { mutableStateOf(false) }
    var showLog by remember { mutableStateOf(false) }

    Card(shape = RoundedCornerShape(8.dp), elevation = 0.dp) {
        Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("训练任务在服务器上以独立进程运行，关闭本窗口不影响训练",
                fontSize = 12.sp, color = TextSecondary)
            Spacer(Modifier.weight(1f))
            Icon(Icons.Default.Refresh, null, tint = EpPrimary,
                modifier = Modifier.clickable { vm.loadJobs() }.padding(4.dp))
            Spacer(Modifier.width(8.dp))
            Button(onClick = { showCreate = true },
                colors = ButtonDefaults.buttonColors(backgroundColor = EpPrimary),
                enabled = !vm.busy) { Text("新建训练任务", color = Color.White) }
        }
    }

    Card(shape = RoundedCornerShape(8.dp), elevation = 0.dp) {
        Column(Modifier.padding(12.dp)) {
            vm.jobs.forEach { j ->
                Row(Modifier.fillMaxWidth().padding(vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Column(Modifier.weight(1f)) {
                        Text(j["name"].str(), fontSize = 14.sp)
                        Text("${j["base_model"].str().substringAfterLast('/')} · " +
                            j["method"].str().uppercase() +
                            (j["train_loss"].str().takeIf { it.isNotBlank() }
                                ?.let { " · loss $it" } ?: "") +
                            (j["val_loss"].str().takeIf { it.isNotBlank() }
                                ?.let { " · val $it" } ?: ""),
                            fontSize = 12.sp, color = TextSecondary)
                    }
                    Text(STATUS_NAMES[j["status"].str()] ?: j["status"].str(),
                        fontSize = 12.sp, color = statusColor(j["status"].str()))
                    TextButton(onClick = { vm.loadJobDetail(j["id"].str()); showLog = true }) {
                        Text("日志", fontSize = 12.sp)
                    }
                    if (j["status"].str() in listOf("pending", "running")) {
                        TextButton(onClick = { vm.cancelJob(j["id"].str()) }) {
                            Text("取消", fontSize = 12.sp, color = EpDanger)
                        }
                    }
                }
                Divider()
            }
            if (vm.jobs.isEmpty())
                Text("暂无训练任务", Modifier.padding(20.dp), fontSize = 13.sp, color = TextPlaceholder)
        }
    }

    if (showCreate) JobCreateDialog(vm) { showCreate = false }

    if (showLog) {
        AlertDialog(
            onDismissRequest = { showLog = false },
            title = {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("训练日志：${vm.currentJob?.get("name").str()}")
                    Spacer(Modifier.weight(1f))
                    TextButton(onClick = {
                        vm.currentJob?.get("id").str().takeIf { it.isNotBlank() }
                            ?.let { vm.loadJobDetail(it) }
                    }) { Text("刷新", fontSize = 12.sp) }
                }
            },
            text = {
                Text(vm.jobLog.ifBlank { "（暂无日志）" }, fontSize = 11.sp,
                    fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace,
                    modifier = Modifier.fillMaxWidth().height(420.dp)
                        .verticalScroll(rememberScrollState())
                        .horizontalScroll(rememberScrollState())
                        .background(Color(0xFF1E1E1E), RoundedCornerShape(6.dp)).padding(10.dp),
                    color = Color(0xFFD4D4D4))
            },
            confirmButton = { TextButton(onClick = { showLog = false }) { Text("关闭") } },
        )
    }
}

@Composable
private fun JobCreateDialog(vm: TrainingViewModel, onClose: () -> Unit) {
    // 收集全部版本供选择
    val versions = remember(vm.datasets) {
        vm.datasets.flatMap { d ->
            (d["versions"] as? kotlinx.serialization.json.JsonArray).orEmpty().mapNotNull { v ->
                v.obj()?.let { "${d["name"].str()} ${it["version"].str()}" to it["id"].str() }
            }
        }
    }
    var name by remember { mutableStateOf("") }
    var vi by remember { mutableStateOf(0) }
    var baseModel by remember { mutableStateOf("/home/lwy/Qwen2.5-7B-Instruct") }
    var method by remember { mutableStateOf("qlora") }
    var mvName by remember { mutableStateOf("") }
    var parentId by remember { mutableStateOf("") }
    var advanced by remember { mutableStateOf(false) }
    var epochs by remember { mutableStateOf("3") }
    var lr by remember { mutableStateOf("0.0002") }
    var batchSize by remember { mutableStateOf("1") }
    var gradAcc by remember { mutableStateOf("8") }
    var loraR by remember { mutableStateOf("64") }
    var maxLen by remember { mutableStateOf("2048") }

    AlertDialog(
        onDismissRequest = onClose,
        title = { Text("新建训练任务") },
        text = {
            Column(Modifier.fillMaxWidth().heightIn(max = 500.dp)
                .verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedTextField(name, { name = it }, label = { Text("任务名称") },
                    singleLine = true, modifier = Modifier.fillMaxWidth())

                Text("数据集版本", fontSize = 12.sp, color = TextSecondary)
                versions.forEachIndexed { i, (label, _) ->
                    Row(verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier.clickable { vi = i }) {
                        Checkbox(checked = vi == i, onCheckedChange = { vi = i })
                        Text(label, fontSize = 13.sp)
                    }
                }
                if (versions.isEmpty())
                    Text("还没有数据集版本，请先在「数据集」页生成", fontSize = 12.sp, color = EpWarning)

                OutlinedTextField(baseModel, { baseModel = it },
                    label = { Text("基础模型（服务器本地路径）") }, singleLine = true,
                    modifier = Modifier.fillMaxWidth())

                Text("训练方式", fontSize = 12.sp, color = TextSecondary)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf("qlora" to "QLoRA（省显存，推荐）", "lora" to "LoRA").forEach { (k, label) ->
                        val active = method == k
                        Text(label, fontSize = 12.sp,
                            color = if (active) Color.White else TextSecondary,
                            modifier = Modifier.background(
                                if (active) EpPrimary else Color(0xFFF0F2F5),
                                RoundedCornerShape(6.dp))
                                .clickable { method = k }
                                .padding(horizontal = 10.dp, vertical = 6.dp))
                    }
                }

                OutlinedTextField(mvName, { mvName = it },
                    label = { Text("模型版本名（如 Judicial-Qwen-7B v1.0，可选）") },
                    singleLine = true, modifier = Modifier.fillMaxWidth())

                if (vm.models.any { it["status"].str() in listOf("Ready", "Published", "Archived") }) {
                    Text("从已有版本继续训练（可选）", fontSize = 12.sp, color = TextSecondary)
                    vm.models.filter { it["adapter_path"].str().isNotBlank() }.forEach { m ->
                        Row(verticalAlignment = Alignment.CenterVertically,
                            modifier = Modifier.clickable {
                                parentId = if (parentId == m["id"].str()) "" else m["id"].str()
                            }) {
                            Checkbox(checked = parentId == m["id"].str(),
                                onCheckedChange = {
                                    parentId = if (it) m["id"].str() else ""
                                })
                            Text(m["name"].str(), fontSize = 13.sp)
                        }
                    }
                }

                Row(verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.clickable { advanced = !advanced }) {
                    Checkbox(checked = advanced, onCheckedChange = { advanced = it })
                    Text("高级配置（技术人员）", fontSize = 13.sp)
                }
                if (advanced) {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(epochs, { epochs = it }, label = { Text("Epoch") },
                            singleLine = true, modifier = Modifier.weight(1f))
                        OutlinedTextField(batchSize, { batchSize = it },
                            label = { Text("Batch Size") }, singleLine = true,
                            modifier = Modifier.weight(1f))
                        OutlinedTextField(gradAcc, { gradAcc = it },
                            label = { Text("梯度累积") }, singleLine = true,
                            modifier = Modifier.weight(1f))
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(lr, { lr = it }, label = { Text("Learning Rate") },
                            singleLine = true, modifier = Modifier.weight(1f))
                        OutlinedTextField(loraR, { loraR = it }, label = { Text("LoRA Rank") },
                            singleLine = true, modifier = Modifier.weight(1f))
                        OutlinedTextField(maxLen, { maxLen = it }, label = { Text("Max Length") },
                            singleLine = true, modifier = Modifier.weight(1f))
                    }
                }
            }
        },
        confirmButton = {
            Button(onClick = {
                if (versions.isEmpty() || name.isBlank()) return@Button
                vm.createJob(buildMap {
                    put("name", name)
                    put("dataset_version_id", versions[vi].second)
                    put("base_model", baseModel)
                    put("method", method)
                    if (mvName.isNotBlank()) put("model_version_name", mvName)
                    if (parentId.isNotBlank()) put("parent_model_version_id", parentId)
                    if (advanced) {
                        put("epochs", epochs.toIntOrNull() ?: 3)
                        put("batch_size", batchSize.toIntOrNull() ?: 1)
                        put("gradient_accumulation", gradAcc.toIntOrNull() ?: 8)
                        put("learning_rate", lr.toDoubleOrNull() ?: 0.0002)
                        put("lora_r", loraR.toIntOrNull() ?: 64)
                        put("max_length", maxLen.toIntOrNull() ?: 2048)
                    }
                })
                onClose()
            }, colors = ButtonDefaults.buttonColors(backgroundColor = EpPrimary),
                enabled = !vm.busy && versions.isNotEmpty()) {
                Text("开始训练", color = Color.White)
            }
        },
        dismissButton = { TextButton(onClick = onClose) { Text("取消") } },
    )
}

// ==================== 模型版本 ====================

@Composable
private fun ModelTab(vm: TrainingViewModel) {
    Card(shape = RoundedCornerShape(8.dp), elevation = 0.dp) {
        Column(Modifier.padding(12.dp)) {
            Text("模型版本只保存微调 Adapter，不覆盖基础模型。本期发布仅代表状态标记，不影响现有对话使用的模型。",
                Modifier.padding(bottom = 8.dp), fontSize = 12.sp, color = TextSecondary)
            vm.models.forEach { m ->
                Row(Modifier.fillMaxWidth().padding(vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Column(Modifier.weight(1f)) {
                        Text(m["name"].str(), fontSize = 14.sp)
                        Text("基础模型 ${m["base_model"].str().substringAfterLast('/')}" +
                            (m["metrics"].obj()?.get("train_loss")?.str()
                                ?.takeIf { it.isNotBlank() }?.let { " · loss $it" } ?: ""),
                            fontSize = 12.sp, color = TextSecondary)
                    }
                    Text(STATUS_NAMES[m["status"].str()] ?: m["status"].str(),
                        fontSize = 12.sp, color = statusColor(m["status"].str()))
                    if (m["status"].str() == "Ready")
                        TextButton(onClick = { vm.publishModel(m["id"].str()) }) {
                            Text("发布", fontSize = 12.sp, color = EpSuccess)
                        }
                    if (m["status"].str() in listOf("Ready", "Published"))
                        TextButton(onClick = { vm.archiveModel(m["id"].str()) }) {
                            Text("归档", fontSize = 12.sp, color = TextSecondary)
                        }
                }
                Divider()
            }
            if (vm.models.isEmpty())
                Text("暂无模型版本，训练完成后会自动生成", Modifier.padding(20.dp),
                    fontSize = 13.sp, color = TextPlaceholder)
        }
    }
}

// ==================== 通用小组件 ====================

@Composable
private fun OutlinedButton(text: String, onClick: () -> Unit) {
    Text(text, fontSize = 13.sp, color = EpPrimary,
        modifier = Modifier
            .background(Color.White, RoundedCornerShape(6.dp))
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 9.dp))
}

@Composable
private fun Pager(total: Int, page: Int, onPage: (Int) -> Unit) {
    if (total <= 20) return
    val pages = (total + 19) / 20
    Row(Modifier.fillMaxWidth().padding(top = 8.dp),
        horizontalArrangement = Arrangement.Center) {
        TextButton(onClick = { if (page > 1) onPage(page - 1) }) { Text("上一页") }
        Text("$page / $pages", fontSize = 12.sp, color = TextSecondary,
            modifier = Modifier.padding(top = 12.dp))
        TextButton(onClick = { if (page < pages) onPage(page + 1) }) { Text("下一页") }
    }
}
