package com.judicialai.desktop.features.dashboard

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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.Button
import androidx.compose.material.ButtonDefaults
import androidx.compose.material.Card
import androidx.compose.material.Icon
import androidx.compose.material.Text
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.List
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Share
import androidx.compose.material.icons.filled.Star
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.app.AppScreen
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.design.theme.BannerGradEnd
import com.judicialai.desktop.design.theme.BannerGradStart
import com.judicialai.desktop.design.theme.EpWarning
import com.judicialai.desktop.design.theme.QuickBlue
import com.judicialai.desktop.design.theme.QuickBlueBg
import com.judicialai.desktop.design.theme.QuickCyan
import com.judicialai.desktop.design.theme.QuickCyanBg
import com.judicialai.desktop.design.theme.QuickGreen
import com.judicialai.desktop.design.theme.QuickGreenBg
import com.judicialai.desktop.design.theme.QuickOrange
import com.judicialai.desktop.design.theme.QuickOrangeBg
import com.judicialai.desktop.design.theme.QuickPurple
import com.judicialai.desktop.design.theme.QuickPurpleBg
import com.judicialai.desktop.design.theme.QuickTeal
import com.judicialai.desktop.design.theme.QuickTealBg
import com.judicialai.desktop.design.theme.TextPlaceholder
import com.judicialai.desktop.design.theme.TextPrimary
import com.judicialai.desktop.design.theme.TextSecondary

private data class QuickEntry(
    val name: String, val desc: String, val icon: ImageVector,
    val fg: Color, val bg: Color, val screen: AppScreen,
)

/** 快速入口：与 Web DashboardView quickEntries 一致 */
private val quickEntries = listOf(
    QuickEntry("信息写作", "自由对话写作", Icons.Default.Edit, QuickBlue, QuickBlueBg, AppScreen.CHAT),
    QuickEntry("公文助手", "文种模板写作", Icons.Default.Star, QuickPurple, QuickPurpleBg, AppScreen.TEMPLATES),
    QuickEntry("知识库", "检索与问答", Icons.Default.List, QuickGreen, QuickGreenBg, AppScreen.KNOWLEDGE),
    QuickEntry("工作流", "任务全流程管理", Icons.Default.Share, QuickOrange, QuickOrangeBg, AppScreen.WORKFLOW),
    QuickEntry("智能PPT", "生成汇报PPT", Icons.Default.PlayArrow, QuickCyan, QuickCyanBg, AppScreen.PPT),
    QuickEntry("格式校验", "文档格式检查", Icons.Default.CheckCircle, QuickTeal, QuickTealBg, AppScreen.FORMAT_CHECK),
)

private val notices = listOf(
    Triple("欢迎使用司法智能办公平台，信息写作已支持参考模板", "刚刚", QuickBlue),
    Triple("文档格式校验能力已上线，可在办公工具中使用", "1天前", QuickGreen),
    Triple("系统公告：请勿在材料中填写涉密信息", "3天前", QuickOrange),
)

/** 首页：1:1 还原 Web DashboardView.vue（Banner + 快速入口 + 左右分栏卡片） */
@Composable
fun DashboardScreen(vm: DashboardViewModel = remember { DashboardViewModel() }) {
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(20.dp),
    ) {
        // Banner
        Box(
            Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp))
                .background(Brush.horizontalGradient(listOf(BannerGradStart, QuickBlue, BannerGradEnd)))
                .padding(horizontal = 48.dp, vertical = 36.dp),
        ) {
            Column {
                Text("欢迎使用司法智能办公平台", fontSize = 26.sp,
                    fontWeight = FontWeight.Bold, color = Color.White)
                Spacer(Modifier.height(10.dp))
                Text("AI 赋能办公，让工作更高效、更智能", fontSize = 14.sp,
                    color = Color.White.copy(alpha = 0.85f))
                Spacer(Modifier.height(22.dp))
                Button(
                    onClick = { AppState.screen = AppScreen.CHAT },
                    colors = ButtonDefaults.buttonColors(backgroundColor = Color(0xFF1A73E8)),
                    shape = RoundedCornerShape(6.dp),
                ) { Text("开始智能写作 →", color = Color.White, fontSize = 14.sp) }
            }
        }

        Row(horizontalArrangement = Arrangement.spacedBy(20.dp)) {
            // 左侧 2/3
            Column(Modifier.weight(2f), verticalArrangement = Arrangement.spacedBy(20.dp)) {
                SectionCard("快速入口") {
                    Row(Modifier.fillMaxWidth()) {
                        quickEntries.forEach { q ->
                            Column(
                                Modifier.weight(1f).clip(RoundedCornerShape(8.dp))
                                    .clickable { AppState.screen = q.screen }
                                    .padding(vertical = 14.dp, horizontal = 6.dp),
                                horizontalAlignment = Alignment.CenterHorizontally,
                            ) {
                                Box(
                                    Modifier.size(52.dp).clip(RoundedCornerShape(12.dp))
                                        .background(q.bg),
                                    contentAlignment = Alignment.Center,
                                ) {
                                    Icon(q.icon, contentDescription = q.name,
                                        tint = q.fg, modifier = Modifier.size(26.dp))
                                }
                                Spacer(Modifier.height(10.dp))
                                Text(q.name, fontSize = 14.sp, fontWeight = FontWeight.SemiBold,
                                    color = TextPrimary)
                                Text(q.desc, fontSize = 12.sp, color = TextSecondary)
                            }
                        }
                    }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(20.dp)) {
                    // 最近文档
                    SectionCard("最近文档", moreText = "全部 >",
                        onMore = { AppState.screen = AppScreen.KNOWLEDGE },
                        modifier = Modifier.weight(1f)) {
                        if (vm.recentDocs.isEmpty()) {
                            EmptyHint("暂无文档，可前往知识库上传")
                        } else vm.recentDocs.forEach { d ->
                            Row(Modifier.padding(vertical = 10.dp),
                                horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                                Icon(Icons.Default.Star, contentDescription = null,
                                    tint = QuickBlue, modifier = Modifier.size(18.dp))
                                Column {
                                    Text(d.title, fontSize = 13.sp, color = TextPrimary,
                                        maxLines = 1, overflow = TextOverflow.Ellipsis)
                                    Text("更新时间：${d.time}　来源：${d.kbName}",
                                        fontSize = 12.sp, color = TextPlaceholder)
                                }
                            }
                        }
                    }
                    // 消息通知
                    SectionCard("消息通知", modifier = Modifier.weight(1f)) {
                        notices.forEach { (title, time, color) ->
                            Row(Modifier.padding(vertical = 10.dp),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                                Box(Modifier.size(30.dp).clip(CircleShape).background(color),
                                    contentAlignment = Alignment.Center) {
                                    Icon(Icons.Default.Notifications, contentDescription = null,
                                        tint = Color.White, modifier = Modifier.size(16.dp))
                                }
                                Column {
                                    Text(title, fontSize = 13.sp, color = TextPrimary,
                                        maxLines = 2, overflow = TextOverflow.Ellipsis)
                                    Text(time, fontSize = 12.sp, color = TextPlaceholder)
                                }
                            }
                        }
                    }
                }
            }

            // 右侧 1/3
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(20.dp)) {
                SectionCard("我的工作流", moreText = "全部 >",
                    onMore = { AppState.screen = AppScreen.WORKFLOW }) {
                    WorkflowPreview()
                }
                SectionCard("常用模板", moreText = "全部 >",
                    onMore = { AppState.screen = AppScreen.TEMPLATES }) {
                    if (vm.templates.isEmpty()) {
                        EmptyHint("暂无模板")
                    } else vm.templates.forEach { t ->
                        Row(
                            Modifier.fillMaxWidth().clip(RoundedCornerShape(6.dp))
                                .clickable { AppState.screen = AppScreen.TEMPLATES }
                                .padding(vertical = 10.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(10.dp),
                        ) {
                            Icon(Icons.Default.Star, contentDescription = null,
                                tint = EpWarning, modifier = Modifier.size(18.dp))
                            Column(Modifier.weight(1f)) {
                                Text(t.name, fontSize = 13.sp, fontWeight = FontWeight.Medium,
                                    color = TextPrimary, maxLines = 1,
                                    overflow = TextOverflow.Ellipsis)
                                Text(t.description.ifBlank { t.category },
                                    fontSize = 12.sp, color = TextPlaceholder,
                                    maxLines = 1, overflow = TextOverflow.Ellipsis)
                            }
                            Tag(t.category)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun WorkflowPreview() {
    val items = listOf(
        Triple("2026年司法行政工作会议", "会议工作流 ｜ 更新于 2026-08-01 14:30", "进行中"),
        Triple("社区矫正宣传活动", "活动工作流 ｜ 更新于 2026-07-30 10:20", "进行中"),
        Triple("基层调研工作任务", "调研工作流 ｜ 更新于 2026-07-28 16:45", "草稿"),
    )
    items.forEach { (name, meta, status) ->
        Column(Modifier.padding(vertical = 10.dp)) {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text(name, fontSize = 13.sp, fontWeight = FontWeight.Medium,
                    color = TextPrimary, modifier = Modifier.weight(1f),
                    maxLines = 1, overflow = TextOverflow.Ellipsis)
                Tag(status)
            }
            Text(meta, fontSize = 12.sp, color = TextPlaceholder)
        }
    }
}

@Composable
fun Tag(text: String, color: Color = Color(0xFF409EFF)) {
    Box(
        Modifier.clip(RoundedCornerShape(4.dp))
            .background(color.copy(alpha = 0.12f))
            .padding(horizontal = 8.dp, vertical = 2.dp),
    ) { Text(text, fontSize = 11.sp, color = color) }
}

@Composable
private fun EmptyHint(text: String) {
    Box(Modifier.fillMaxWidth().padding(vertical = 24.dp), contentAlignment = Alignment.Center) {
        Text(text, fontSize = 13.sp, color = TextSecondary)
    }
}

@Composable
fun SectionCard(
    title: String,
    moreText: String? = null,
    onMore: (() -> Unit)? = null,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    Card(
        modifier = modifier.fillMaxWidth(),
        shape = RoundedCornerShape(10.dp),
        elevation = 0.dp,
        backgroundColor = Color.White,
    ) {
        Column {
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 14.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(title, fontSize = 15.sp, fontWeight = FontWeight.SemiBold,
                    color = TextPrimary, modifier = Modifier.weight(1f))
                if (moreText != null) {
                    Text(moreText, fontSize = 12.sp, color = Color(0xFF409EFF),
                        modifier = Modifier.clip(RoundedCornerShape(4.dp))
                            .clickable { onMore?.invoke() }.padding(4.dp))
                }
            }
            Box(Modifier.fillMaxWidth().height(1.dp).background(Color(0xFFF2F4F8)))
            Column(Modifier.padding(horizontal = 20.dp, vertical = 8.dp)) { content() }
        }
    }
}

