package com.judicialai.desktop.features.ppt

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.Button
import androidx.compose.material.Card
import androidx.compose.material.Divider
import androidx.compose.material.DropdownMenu
import androidx.compose.material.DropdownMenuItem
import androidx.compose.material.MaterialTheme
import androidx.compose.material.OutlinedButton
import androidx.compose.material.OutlinedTextField
import androidx.compose.material.Text
import androidx.compose.material.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.dp
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.core.platform.pickSaveFile
import com.judicialai.desktop.core.platform.rememberServerImage
import com.judicialai.desktop.core.utils.str
import com.judicialai.desktop.design.theme.SecondaryText

/**
 * 三栏工作台：左 = 页面导航（只读缩略列表）；中 = PPT 视觉焦点（模板渲染预览 + 直接编辑）；
 * 右 = AI 助手（单页局部编辑优先：润色/扩写/精简/重写/自定义，结构调整次之）。
 */
@Composable
fun PptWorkbench(vm: PptViewModel) {
    Row(Modifier.fillMaxSize()) {
        // ---- 左栏：页面导航 ----
        Column(Modifier.width(200.dp).fillMaxHeight().background(
            MaterialTheme.colors.surface).padding(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("页面（${vm.slides.size}）", style = MaterialTheme.typography.subtitle2,
                    modifier = Modifier.weight(1f))
            }
            Spacer(Modifier.height(6.dp))
            LazyColumn(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                itemsIndexed(vm.slides, key = { i, _ -> i }) { i, s ->
                    val selected = i == vm.selected
                    Card(
                        elevation = if (selected) 4.dp else 1.dp,
                        backgroundColor = if (selected)
                            MaterialTheme.colors.primary.copy(alpha = 0.12f)
                        else MaterialTheme.colors.background,
                    ) {
                        TextButton(onClick = { vm.selected = i },
                            modifier = Modifier.fillMaxWidth()) {
                            Column(Modifier.fillMaxWidth()) {
                                Text("${i + 1} · ${slideTypeLabel(s.type)}",
                                    style = MaterialTheme.typography.caption,
                                    color = MaterialTheme.colors.primary)
                                Text(s.title.ifBlank { "（无标题）" },
                                    style = MaterialTheme.typography.body2, maxLines = 2)
                            }
                        }
                    }
                }
            }
        }

        Divider(Modifier.fillMaxHeight().width(1.dp))

        // ---- 中栏：PPT 视觉焦点 + 直接编辑 ----
        val i = vm.selected.coerceIn(0, (vm.slides.size - 1).coerceAtLeast(0))
        val slide = vm.slides.getOrNull(i)
        // 切换模板 / 手动刷新时递增，避免同一 URL 的预览图被缓存成旧版
        var previewTick by remember { mutableStateOf(0) }
        Column(Modifier.weight(1f).fillMaxHeight().verticalScroll(rememberScrollState())
            .padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            if (slide == null) {
                Text("暂无页面", color = SecondaryText)
            } else {
                // 模板选择：在这里也能换，换完立刻按新模板重渲染预览
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("模板", style = MaterialTheme.typography.subtitle2)
                    Spacer(Modifier.width(8.dp))
                    var tplOpen by remember { mutableStateOf(false) }
                    val curName = vm.templates
                        .firstOrNull { it["id"].str() == vm.templateId }
                        ?.get("name").str().ifBlank { "默认模板" }
                    Box {
                        OutlinedButton(onClick = { tplOpen = true },
                            colors = sel(false)) { Text("$curName ▾") }
                        DropdownMenu(tplOpen, { tplOpen = false }) {
                            vm.templates.forEach { t ->
                                DropdownMenuItem(onClick = {
                                    vm.templateId = t["id"].str()
                                    tplOpen = false
                                    previewTick++
                                    vm.refreshPreview()
                                }) { Text(t["name"].str()) }
                            }
                        }
                    }
                    Spacer(Modifier.width(8.dp))
                    TextButton(enabled = !vm.previewBusy, onClick = {
                        previewTick++
                        vm.refreshPreview()
                    }) { Text(if (vm.previewBusy) "渲染中…" else "刷新预览") }
                }

                // 预览（16:9 视觉焦点）：优先显示服务端按当前模板真实渲染的 PNG；
                // 服务端未渲染成功时回退为结构化预览卡
                Card(Modifier.fillMaxWidth().height(300.dp), elevation = 3.dp) {
                    val rawUrl = vm.previewPages.getOrNull(i)
                    val pageUrl = rawUrl?.let {
                        it + (if (it.contains("?")) "&" else "?") + "_=" + previewTick
                    }
                    val img = rememberServerImage(AppState.api, pageUrl)
                    if (img != null) {
                        Image(img, contentDescription = slide.title,
                            modifier = Modifier.fillMaxSize(),
                            contentScale = ContentScale.Fit)
                    } else {
                        Column(Modifier.fillMaxSize()) {
                            Box(Modifier.fillMaxWidth().height(6.dp)
                                .background(MaterialTheme.colors.primary))
                            Column(Modifier.padding(20.dp)) {
                                Text(slide.title.ifBlank { "（无标题）" },
                                    style = MaterialTheme.typography.h6)
                                Spacer(Modifier.height(10.dp))
                                slide.points().take(6).forEach { p ->
                                    Text("• $p", style = MaterialTheme.typography.body2,
                                        modifier = Modifier.padding(vertical = 2.dp))
                                }
                                if (slide.points().size > 6) {
                                    Text("……共 ${slide.points().size} 条要点",
                                        style = MaterialTheme.typography.caption,
                                        color = SecondaryText)
                                }
                            }
                        }
                    }
                }
                Text(
                    if (vm.previewPages.getOrNull(i) != null)
                        "预览由所选模板真实渲染，与导出效果一致"
                    else if (vm.previewBusy) "正在按模板渲染预览…"
                    else "模板渲染预览暂不可用，当前为结构示意（不影响导出效果）",
                    style = MaterialTheme.typography.caption, color = SecondaryText)
                if (slide.sources.isNotEmpty()) {
                    Text("内容依据：" + slide.sources.joinToString("、"),
                        style = MaterialTheme.typography.caption, color = SecondaryText)
                }

                // 直接编辑
                OutlinedTextField(slide.title, { slide.title = it },
                    label = { Text("本页标题") }, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(slide.pointsText, { slide.pointsText = it },
                    label = { Text("要点（一行一条）") },
                    modifier = Modifier.fillMaxWidth().heightIn(min = 100.dp, max = 220.dp))

                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = { vm.backToOutline() }) { Text("返回大纲") }
                    OutlinedButton(enabled = !vm.busy,
                        onClick = { vm.saveDraft() }) { Text("保存草稿") }
                    Button(enabled = !vm.busy, onClick = {
                        val target = pickSaveFile(
                            (vm.outlineTitle.ifBlank { "演示文稿" }) + ".pptx") ?: return@Button
                        vm.generateAndExport(target)
                    }) { Text(if (vm.busy) "生成中…" else "生成并导出 PPT") }
                }
                PptStatus(vm)
            }
        }

        Divider(Modifier.fillMaxHeight().width(1.dp))

        // ---- 右栏：AI 助手 ----
        Column(Modifier.width(280.dp).fillMaxHeight().background(
            MaterialTheme.colors.surface).padding(10.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("AI 助手", style = MaterialTheme.typography.subtitle2)
            Text("当前：第 ${i + 1} 页（${slideTypeLabel(slide?.type ?: "")}）",
                style = MaterialTheme.typography.caption, color = SecondaryText)

            Text("修改本页", style = MaterialTheme.typography.caption, color = SecondaryText)
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                OutlinedButton(enabled = !vm.aiBusy,
                    onClick = { vm.aiSlide("rewrite") }) { Text("重写") }
                OutlinedButton(enabled = !vm.aiBusy,
                    onClick = { vm.aiSlide("expand") }) { Text("扩写") }
                OutlinedButton(enabled = !vm.aiBusy,
                    onClick = { vm.aiSlide("condense") }) { Text("精简") }
            }
            OutlinedButton(enabled = !vm.aiBusy, modifier = Modifier.fillMaxWidth(),
                onClick = {
                    vm.aiSlide("custom", "润色本页文字：保持事实、数字与来源不变，表达更流畅正式")
                }) { Text("润色本页") }

            OutlinedTextField(vm.aiInstruction, { vm.aiInstruction = it },
                label = { Text("对 AI 说怎么改这一页") },
                modifier = Modifier.fillMaxWidth().heightIn(min = 70.dp, max = 140.dp))
            Button(enabled = !vm.aiBusy && vm.aiInstruction.isNotBlank(),
                modifier = Modifier.fillMaxWidth(),
                onClick = {
                    vm.aiSlide("custom", vm.aiInstruction.trim())
                    vm.aiInstruction = ""
                }) { Text(if (vm.aiBusy) "AI 处理中…" else "发送") }

            Divider()
            Text("页面结构", style = MaterialTheme.typography.caption, color = SecondaryText)
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                TextButton(enabled = !vm.aiBusy,
                    onClick = { vm.aiStructure("add") }) { Text("后增一页") }
                TextButton(enabled = !vm.aiBusy,
                    onClick = { vm.aiStructure("split") }) { Text("拆分本页") }
                TextButton(enabled = !vm.aiBusy,
                    onClick = { vm.aiStructure("merge") }) { Text("合并下页") }
            }

            vm.aiNote?.let {
                Text(it, style = MaterialTheme.typography.caption,
                    color = if (it.contains("已")) MaterialTheme.colors.primary
                    else MaterialTheme.colors.error)
            }
        }
    }
}
