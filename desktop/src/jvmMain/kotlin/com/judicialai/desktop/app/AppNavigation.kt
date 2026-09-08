package com.judicialai.desktop.app

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Create
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Email
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.List
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Share

import androidx.compose.ui.graphics.vector.ImageVector

/**
 * 页面导航：与 Web 端路由（router/index.js）一一对应。
 * SETTINGS 不在侧边栏菜单中，由顶栏用户下拉「服务器连接设置」进入。
 */
enum class AppScreen(val title: String, val icon: ImageVector) {
    DASHBOARD("首页", Icons.Default.Home),
    WRITING("智能写作", Icons.Default.Edit),
    CHAT("对话助手", Icons.Default.Email),
    DOCUMENTS("我的文档", Icons.Default.Create),
    TEMPLATES("模板中心", Icons.Default.Star),
    KNOWLEDGE("知识库", Icons.Default.List),
    WORKFLOW("工作流", Icons.Default.Share),
    PPT("PPT助手", Icons.Default.PlayArrow),
    FORMAT_CHECK("格式校验", Icons.Default.CheckCircle),
    TRAINING("数据资产中心", Icons.Default.Star),
    ADMIN("管理后台", Icons.Default.Email),
    SETTINGS("服务器连接设置", Icons.Default.Settings),
}

/** 侧边栏菜单项：level 1 = 分组标题（智能写作），level 2 = 分组子项 */
data class MenuEntry(
    val screen: AppScreen?,
    val label: String,
    val icon: ImageVector?,
    val children: List<AppScreen> = emptyList(),
    val adminOnly: Boolean = false,
)

/** 菜单结构 1:1 对应 AppLayout.vue el-menu */
object AppMenu {
    val entries: List<MenuEntry> = listOf(
        MenuEntry(AppScreen.DASHBOARD, "首页", Icons.Default.Home),
        MenuEntry(
            null, "智能写作", Icons.Default.Edit,
            children = listOf(AppScreen.WRITING, AppScreen.DOCUMENTS, AppScreen.TEMPLATES, AppScreen.KNOWLEDGE, AppScreen.CHAT),
        ),
        MenuEntry(AppScreen.WORKFLOW, "工作流", Icons.Default.Share),
        MenuEntry(AppScreen.PPT, "PPT助手", Icons.Default.PlayArrow),
        MenuEntry(AppScreen.FORMAT_CHECK, "格式校验", Icons.Default.CheckCircle),
        MenuEntry(AppScreen.TRAINING, "数据资产中心", Icons.Default.Star),
        MenuEntry(AppScreen.ADMIN, "管理后台", Icons.Default.Settings, adminOnly = true),
    )

    /** 顶栏标题（对应 AppLayout.vue TITLES） */
    fun titleOf(screen: AppScreen): String = screen.title
}

