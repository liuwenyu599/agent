package com.judicialai.desktop.features.ppt

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.Button
import androidx.compose.material.ButtonDefaults
import androidx.compose.material.Card
import androidx.compose.material.CircularProgressIndicator
import androidx.compose.material.LinearProgressIndicator
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.core.platform.pickSaveFile
import com.judicialai.desktop.core.platform.rememberServerImage
import com.judicialai.desktop.design.components.AppButton
import com.judicialai.desktop.design.components.AppButtonKind
import com.judicialai.desktop.design.components.AppDialog
import com.judicialai.desktop.design.theme.AppBg
import com.judicialai.desktop.design.theme.Ink
import com.judicialai.desktop.design.theme.Ink2
import com.judicialai.desktop.design.theme.Line
import com.judicialai.desktop.design.theme.Muted
import com.judicialai.desktop.design.theme.Primary
import com.judicialai.desktop.design.theme.SecondaryText
import com.judicialai.desktop.design.theme.Surface
import com.judicialai.desktop.design.theme.SurfaceDeep
import kotlin.math.abs

/** 未生成页的占位底色（灰色） */
private val PlaceholderGray = Color(0xFFF1F3F6)
/** 底部状态栏进度条浅蓝填充（与既有工作台一致） */
private val ProgressBlue = Color(0xFF64A8F0)
/** 缩略图懒加载窗口：只加载当前页 ±2 页 */
private const val LAZY_WINDOW = 2

/**
 * 异步生成工作台（三栏）：
 * 左=缩略图（未生成的页灰色占位「生成中」）｜中=当前页大图（加载中骨架屏）｜右=AI 面板；
 * 底部=「已生成 3 页 · 正在生成页面…」+ 停止等待 / 下载 PPTX。
 */
@Composable
fun PptAsyncWorkbench(vm: PptViewModel) {
    val job = vm.job ?: return
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.weight(1f).fillMaxWidth()) {
            JobThumbRail(vm, job)
            Box(Modifier.width(1.dp).fillMaxHeight().background(Line))
            JobPreviewPane(vm, job)
            Box(Modifier.width(1.dp).fillMaxHeight().background(Line))
            AiPanel(vm) // 右栏复用工作台的 AI 面板
        }
        JobStatusBar(vm, job)
    }
}

/**
 * PPTAgent 追问框：复用项目统一的 [AppDialog]（与生成前预检确认框同一套组件与样式）。
 * 后端刻意不自动代答（自动代答等于替用户编需求），所以这一步必须落到用户头上：
 * 用户可以自己回答，也可以明确选择「让 AI 按它的判断继续」（后端约定空串即此意）。
 */
@Composable
fun PptJobClarifyDialog(vm: PptViewModel, job: PptJobProgress) {
    // 后端万一没给问题文本（只有状态），也要让用户能作答，不能让人卡死
    val question = job.question?.takeIf { it.isNotBlank() }
        ?: "AI 需要补充信息才能继续生成，请说明你的要求"
    var answer by remember(job.jobId, question) { mutableStateOf("") }
    AppDialog(
        onDismissRequest = { vm.cancelJob() },
        title = "AI 需要你补充一点信息",
        subtitle = "回答后会接着刚才的进度继续生成，不会从头再来。",
        width = 560.dp,
        actions = {
            AppButton("停止等待", onClick = { vm.cancelJob() },
                kind = AppButtonKind.SECONDARY)
            Spacer(Modifier.width(8.dp))
            AppButton("让 AI 按它的判断继续",
                onClick = { vm.submitClarify("") }, kind = AppButtonKind.SECONDARY)
            Spacer(Modifier.width(8.dp))
            AppButton("提交并继续", onClick = { vm.submitClarify(answer.trim()) },
                enabled = !job.answering)
        },
    ) {
        Text(question, fontSize = 13.5.sp, color = Ink, lineHeight = 20.sp)
        Spacer(Modifier.height(10.dp))
        OutlinedTextField(
            value = answer, onValueChange = { answer = it },
            label = { Text("你的回答（留空表示让 AI 自行判断）") },
            modifier = Modifier.fillMaxWidth().heightIn(min = 90.dp, max = 160.dp),
        )
        job.answerError?.let {
            Text(it, fontSize = 12.sp, color = MaterialTheme.colors.error)
        }
    }
}

// ================= 左栏：缩略图 =================

@Composable
private fun JobThumbRail(vm: PptViewModel, job: PptJobProgress) {
    val total = job.displayTotal(vm.slides.size)
    Column(
        Modifier.width(196.dp).fillMaxHeight().background(Surface).padding(10.dp),
    ) {
        // 总页数只在共享卷可用时才准，为 0 时只报已生成页数，不出现「0/0」
        Text(
            if (job.knownTotal != null) "页面（${job.donePages}/$total）"
            else "已生成 ${job.donePages} 页",
            fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = Ink)
        Spacer(Modifier.height(2.dp))
        Text(job.stageText, fontSize = 11.sp, color = Muted, maxLines = 2, lineHeight = 15.sp)
        Spacer(Modifier.height(8.dp))
        LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            items(count = total) { index ->
                JobThumbItem(job, index + 1)
            }
        }
    }
}

@Composable
private fun JobThumbItem(job: PptJobProgress, n: Int) {
    val selected = n == job.selectedPage
    val page = job.pageOf(n)
    val ready = page?.pngReady == true
    // 懒加载：只请求当前页 ±2 页的 PNG；未出图的页不发请求，直接占位
    val inWindow = abs(n - job.selectedPage) <= LAZY_WINDOW
    val img = rememberServerImage(AppState.api,
        if (inWindow) pptJobImageUrl(job.jobId, page) else null)
    Box(Modifier.fillMaxWidth().clickable { job.selectedPage = n }) {
        Box(
            Modifier.fillMaxWidth()
                .aspectRatio(16f / 9f)
                .clip(RoundedCornerShape(6.dp))
                .background(if (ready) Color.White else PlaceholderGray)
                .border(1.dp, if (selected) Primary else Line, RoundedCornerShape(6.dp)),
        ) {
            when {
                img != null -> Image(img, contentDescription = "第 $n 页",
                    modifier = Modifier.fillMaxSize(), contentScale = ContentScale.Fit)
                ready -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp,
                        color = Primary)
                }
                else -> Column(
                    Modifier.fillMaxSize().padding(8.dp),
                    verticalArrangement = Arrangement.Center,
                ) {
                    Text("$n", fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = Muted)
                    Text("生成中", fontSize = 10.5.sp, color = Muted)
                }
            }
        }
        // 选中态：左侧 3dp 深蓝竖条
        if (selected) {
            Box(
                Modifier.align(Alignment.CenterStart)
                    .width(3.dp).height(56.dp)
                    .clip(RoundedCornerShape(topEnd = 2.dp, bottomEnd = 2.dp))
                    .background(Primary),
            )
        }
    }
}

// ================= 中栏：当前页大图 =================

@Composable
private fun JobPreviewPane(vm: PptViewModel, job: PptJobProgress) {
    val total = job.displayTotal(vm.slides.size)
    val n = job.selectedPage.coerceIn(1, total)
    val page = job.pageOf(n)
    val img = rememberServerImage(AppState.api, pptJobImageUrl(job.jobId, page))

    Column(
        Modifier.fillMaxHeight().verticalScroll(rememberScrollState())
            .background(AppBg).padding(32.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            // 总页数未知时不显示「/ 共 N 页」
            Text(
                if (job.knownTotal != null) "第 $n 页 / 共 $total 页" else "第 $n 页",
                fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = Ink)
            Spacer(Modifier.width(10.dp))
            Text(job.stageText, fontSize = 12.sp, color = Ink2, maxLines = 1)
            Spacer(Modifier.weight(1f))
            TextButton(onClick = { vm.dismissJob() }) {
                Text("← 返回编辑", color = Primary, fontSize = 12.5.sp)
            }
        }

        Card(
            modifier = Modifier.fillMaxWidth().aspectRatio(16f / 9f),
            shape = RoundedCornerShape(8.dp),
            elevation = 4.dp,
            backgroundColor = Color.White,
        ) {
            when {
                img != null -> Image(img, contentDescription = "第 $n 页",
                    modifier = Modifier.fillMaxSize(), contentScale = ContentScale.Fit)
                page?.pngReady == true -> Box(Modifier.fillMaxSize(),
                    contentAlignment = Alignment.Center) {
                    CircularProgressIndicator(Modifier.size(24.dp), strokeWidth = 2.dp,
                        color = Primary)
                }
                job.status == PptJobStatus.FAILED -> JobErrorBox(job.errorMsg)
                else -> PreviewSkeleton()
            }
        }

        Text(jobHintText(job), fontSize = 11.5.sp, color = SecondaryText)
        // 回退本地渲染是有意行为（宁可给能打开的文件），要明确说清楚，否则用户以为排版出错
        pptRendererNote(job.renderer)?.let {
            Text(it, fontSize = 11.5.sp, color = Ink2, lineHeight = 17.sp)
        }
        job.exportError?.let {
            Text("保存失败：$it", fontSize = 11.5.sp, color = MaterialTheme.colors.error)
        }
        job.exportedPath?.let {
            Text("已保存：$it", fontSize = 11.5.sp, color = Primary)
        }
    }
}

private fun jobHintText(job: PptJobProgress): String = when (job.status) {
    PptJobStatus.SUBMITTED -> "任务已提交，服务端正在排队，可先去其他页面"
    PptJobStatus.GENERATING -> "每生成完一页就会出现在左侧，可点选查看大图"
    PptJobStatus.CLARIFYING -> "AI 需要你补充一点信息，回答后会接着刚才的进度继续生成"
    PptJobStatus.DONE -> if (job.exportedPath == null)
        "全部页面已生成，并已保存到“我的作品”；需要本地文件时点击下方“下载 PPTX”"
    else
        "全部页面已生成；服务端“我的作品”中已保留，也可再次下载到其他位置"
    PptJobStatus.FAILED -> "生成未完成，可点击「重试」用同一份大纲再生成一次"
    PptJobStatus.CANCELLED -> "已停止等待本次生成，可点击「重新开始」再生成一次"
    PptJobStatus.IDLE -> ""
}

@Composable
private fun JobErrorBox(message: String?) {
    Column(
        Modifier.fillMaxSize().padding(28.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("生成失败", fontSize = 15.sp, fontWeight = FontWeight.SemiBold,
            color = MaterialTheme.colors.error)
        Text(message?.takeIf { it.isNotBlank() } ?: "服务端未给出具体原因",
            fontSize = 12.sp, color = Ink2, lineHeight = 18.sp)
    }
}

// ================= 底部状态栏 =================

@Composable
private fun JobStatusBar(vm: PptViewModel, job: PptJobProgress) {
    val running = job.isActive || job.exporting
    Column {
        if (running) {
            LinearProgressIndicator(
                modifier = Modifier.fillMaxWidth().height(3.dp),
                color = ProgressBlue, backgroundColor = Line,
            )
        }
        Box(Modifier.fillMaxWidth().height(1.dp).background(Line))
        Row(
            Modifier.fillMaxWidth().height(56.dp).background(SurfaceDeep)
                .padding(horizontal = 20.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            // 服务端不知道总页数时（跨机部署）不显示「0/N 页」，只报已生成页数 + 阶段
            Text(
                job.knownTotal?.let { "进度：${job.donePages}/$it 页 · ${job.stageText}" }
                    ?: if (job.donePages > 0) "已生成 ${job.donePages} 页 · ${job.stageText}"
                    else job.stageText,
                fontSize = 12.5.sp,
                color = when (job.status) {
                    PptJobStatus.FAILED -> MaterialTheme.colors.error
                    PptJobStatus.DONE -> Primary
                    else -> Ink2
                })
            if (job.elapsedSeconds > 0) {
                Spacer(Modifier.width(12.dp))
                Text("已用时 ${formatJobDuration(job.elapsedSeconds)}" +
                    (job.estimatedRemaining?.let { " · 预计还需 ${formatJobDuration(it)}" } ?: ""),
                    fontSize = 11.5.sp, color = Muted)
            }
            job.transientError?.let {
                Spacer(Modifier.width(12.dp))
                Text(it, fontSize = 11.5.sp, color = MaterialTheme.colors.error, maxLines = 1)
            }
            Spacer(Modifier.weight(1f))

            when (job.status) {
                PptJobStatus.SUBMITTED, PptJobStatus.GENERATING -> {
                    // 语义是停止等待，不是终止生成（PPTAgent 侧跑不完也拦不住）
                    TextButton(onClick = { vm.cancelJob() }) {
                        Text("停止等待", fontSize = 12.5.sp, color = MaterialTheme.colors.error)
                    }
                }
                PptJobStatus.CLARIFYING -> {
                    TextButton(onClick = { vm.cancelJob() }) {
                        Text("停止等待", fontSize = 12.5.sp, color = MaterialTheme.colors.error)
                    }
                }
                PptJobStatus.DONE -> {
                    OutlinedButton(enabled = !job.exporting, onClick = {
                        val target = pickSaveFile(
                            (vm.outlineTitle.ifBlank { "演示文稿" }) + ".pptx")
                        vm.downloadJobResult(target)
                    }) {
                        Text(if (job.exporting) "保存中…" else "下载 PPTX", fontSize = 12.5.sp)
                    }
                    Spacer(Modifier.width(10.dp))
                    Button(
                        enabled = !job.exporting,
                        onClick = { vm.dismissJob() },
                        colors = ButtonDefaults.buttonColors(backgroundColor = Primary),
                        shape = RoundedCornerShape(8.dp),
                    ) { Text("完成，返回编辑", color = Color.White, fontSize = 13.sp) }
                }
                PptJobStatus.FAILED -> {
                    TextButton(onClick = { vm.dismissJob() }) {
                        Text("返回编辑", fontSize = 12.5.sp, color = Ink2)
                    }
                    Spacer(Modifier.width(10.dp))
                    Button(
                        onClick = { vm.retryJob() },
                        colors = ButtonDefaults.buttonColors(backgroundColor = Primary),
                        shape = RoundedCornerShape(8.dp),
                    ) { Text("重试", color = Color.White, fontSize = 13.sp) }
                }
                PptJobStatus.CANCELLED -> {
                    TextButton(onClick = { vm.dismissJob() }) {
                        Text("返回编辑", fontSize = 12.5.sp, color = Ink2)
                    }
                    Spacer(Modifier.width(10.dp))
                    Button(
                        onClick = { vm.retryJob() },
                        colors = ButtonDefaults.buttonColors(backgroundColor = Primary),
                        shape = RoundedCornerShape(8.dp),
                    ) { Text("重新开始", color = Color.White, fontSize = 13.sp) }
                }
                PptJobStatus.IDLE -> Unit
            }
        }
    }
}
