package com.judicialai.desktop.app

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Group
import androidx.compose.material.icons.filled.Groups
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.LibraryBooks
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Share
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.filled.Storage
import androidx.compose.material.icons.filled.Tune
import androidx.compose.ui.graphics.vector.ImageVector

/**
 * 页面枚举：与后端能力一一对应，不做前端假页面。
 *
 * v3.2 信息架构：
 * - Agent 不再是独立导航项，而是按 department_code 自动绑定的能力层，
 *   只服务于智能写作 / 模板中心 / 知识检索 / PPT 等具体任务；
 * - 业务导航固定 8 项，管理入口按角色出现。
 * SETTINGS 不进入导航，由用户菜单进入。
 */
enum class AppScreen(val title: String, val icon: ImageVector) {
    HOME("工作台", Icons.Default.Home),
    WRITING("智能写作", Icons.Default.Edit),
    TEMPLATES("模板中心", Icons.Default.Star),
    PPT("PPT 助手", Icons.Default.PlayArrow),
    FORMAT_CHECK("格式校验", Icons.Default.CheckCircle),

    DEPARTMENT("科室空间", Icons.Default.Groups),
    KNOWLEDGE("知识库", Icons.Default.LibraryBooks),
    CHAT("历史记录", Icons.Default.History),

    // DOCUMENTS 保留实现，入口收在「个人中心」，不占用主导航；
    // WORKFLOW（工作流程）入口在「科室空间」界面底部：本科室工作流程列表 + 进入平台
    DOCUMENTS("我的文档", Icons.Default.Description),
    WORKFLOW("工作流程", Icons.Default.Share),

    TRAINING("数据资产中心", Icons.Default.Storage),
    ADMIN("管理后台", Icons.Default.Settings),
    SETTINGS("服务器连接设置", Icons.Default.Settings),
}

/**
 * 导航项：一个具体落点。
 * adminTab 仅在 screen = ADMIN 时生效，用于直达管理后台对应 Tab（Tab 全部为后端真实能力）。
 */
data class NavItem(
    val screen: AppScreen,
    val label: String = screen.title,
    val icon: ImageVector = screen.icon,
    val desc: String = "",
    val adminTab: Int = 0,
)

/** 导航分组：核心生产力 / 科室与知识 / 管理能力，三组不同层级 */
data class NavGroup(
    val key: String,
    val title: String,
    val desc: String,
    val items: List<NavItem>,
)

object AppNav {

    /** 核心生产力：首页 2×2 彩色卡同源，也是抽屉里的一级入口 */
    val coreItems: List<NavItem> = listOf(
        NavItem(AppScreen.WRITING, desc = "描述工作，助手按本科室口径成稿"),
        NavItem(AppScreen.TEMPLATES, desc = "系统模板 · 科室模板 · 我的模板"),
        NavItem(AppScreen.PPT, desc = "从材料生成汇报演示文稿"),
        NavItem(AppScreen.FORMAT_CHECK, desc = "公文规范逐条检查"),
    )

    /** 科室空间：本科室资源空间（智能助手 + 常用业务 + 工作流程 + 知识 + 模板），不是 Agent 选择器 */
    val departmentItems: List<NavItem> = listOf(
        NavItem(AppScreen.DEPARTMENT, desc = "智能助手、常用业务、知识与模板"),
    )

    val businessItems: List<NavItem> = listOf(
        NavItem(AppScreen.KNOWLEDGE, desc = "公共 + 本科室 + 个人知识"),
        NavItem(AppScreen.CHAT, desc = "我生成的对话、文档、PPT 与工作流程"),
    )

    /** 管理后台 Tab 序号与 AdminScreen 内 TabRow 顺序一致（0 统计 / 1 用户 / 2 知识库 / 3 文档） */
    val adminItems: List<NavItem> = listOf(
        NavItem(AppScreen.ADMIN, "用户与组织", Icons.Default.Group, "账号、科室与角色", adminTab = 1),
        NavItem(AppScreen.TRAINING, desc = "语料、样本与数据集"),
    )

    /** 科室管理员：只暴露本科室范围内的维护入口 */
    val knowledgeAdminItems: List<NavItem> = listOf(
        NavItem(AppScreen.DEPARTMENT, "智能助手配置", Icons.Default.Tune,
            "业务口径、工作要求、推荐任务与知识模板关联"),
    )

    /** 全局导航抽屉分组 */
    val groups: List<NavGroup> = listOf(
        NavGroup("core", "核心生产力", "日常公文办公的主入口", coreItems),
        NavGroup("dept", "科室空间", "智能助手、工作流程、知识与模板", departmentItems),
        NavGroup("business", "知识与记录", "资料与归档", businessItems),
    )

    /** 抽屉分组 = 业务分组 + 角色化管理分组 */
    fun drawerGroups(): List<NavGroup> {
        val manage = mutableListOf<NavItem>()
        if (AppState.isKnowledgeAdmin || AppState.isDeveloper) manage += knowledgeAdminItems
        if (AppState.isDeveloper) manage += adminItems
        return if (manage.isEmpty()) groups
        else groups + NavGroup("manage", "管理能力", "仅在权限范围内可见", manage)
    }

    /** 全局导航搜索用扁平列表 */
    fun flat(): List<NavItem> = drawerGroups().flatMap { it.items }

    /** 当前页面所属分组（用于顶栏面包屑） */
    fun groupOf(screen: AppScreen): NavGroup? =
        drawerGroups().firstOrNull { g -> g.items.any { it.screen == screen } }

    /** 页面显示标题 */
    fun titleOf(screen: AppScreen): String = screen.title
}
