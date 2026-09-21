package com.judicialai.desktop.app

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Assignment
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Group
import androidx.compose.material.icons.filled.Groups
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.List
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Share
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.filled.Storage
import androidx.compose.material.icons.filled.Tune
import androidx.compose.ui.graphics.vector.ImageVector

/**
 * 页面枚举：与后端能力一一对应，不做前端假页面。
 * SETTINGS 不进入导航，由用户菜单进入。
 */
enum class AppScreen(val title: String, val icon: ImageVector) {
    HOME("工作台", Icons.Default.Home),
    DEPARTMENT("科室空间", Icons.Default.Groups),
    WRITING("智能写作", Icons.Default.Edit),
    TEMPLATES("模板中心", Icons.Default.Star),
    PPT("PPT 助手", Icons.Default.PlayArrow),
    FORMAT_CHECK("格式校验", Icons.Default.CheckCircle),

    KNOWLEDGE("知识库", Icons.Default.List),
    APPROVAL("审批", Icons.Default.Assignment),
    DOCUMENTS("我的文档", Icons.Default.Description),
    CHAT("历史任务", Icons.Default.History),
    WORKFLOW("工作流", Icons.Default.Share),

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

/** 导航分组：核心生产力 / 业务能力 / 管理能力，三组不同层级，不再平铺成一列菜单 */
data class NavGroup(
    val key: String,
    val title: String,
    val desc: String,
    val items: List<NavItem>,
)

object AppNav {

    /** 首页四大入口（与首页 2×2 彩色卡同源） */
    val coreItems: List<NavItem> = listOf(
        NavItem(AppScreen.WRITING, desc = "起草、续写、润色与公文成稿"),
        NavItem(AppScreen.TEMPLATES, desc = "按文种挑选规范模板"),
        NavItem(AppScreen.PPT, desc = "从材料生成汇报演示文稿"),
        NavItem(AppScreen.FORMAT_CHECK, desc = "公文规范逐条检查"),
    )

    /** 科室空间：当前用户所属科室的 Agent 与知识边界 */
    val departmentItems: List<NavItem> = listOf(
        NavItem(AppScreen.DEPARTMENT, desc = "本科室 Agent、知识与模板"),
    )

    val businessItems: List<NavItem> = listOf(
        NavItem(AppScreen.KNOWLEDGE, desc = "资料入库、索引与检索"),
        NavItem(AppScreen.APPROVAL, desc = "待办、我发起的、已处理"),
        NavItem(AppScreen.DOCUMENTS, desc = "文档与历史版本"),
        NavItem(AppScreen.CHAT, desc = "历史对话与写作记录"),
        NavItem(AppScreen.WORKFLOW, desc = "任务全流程编排"),
    )

    /** 管理后台 Tab 序号与 AdminScreen 内 TabRow 顺序一致（0 统计 / 1 用户 / 2 知识库 / 3 文档 / 4 会话 / 5 审批配置） */
    val adminItems: List<NavItem> = listOf(
        NavItem(AppScreen.ADMIN, "用户与角色", Icons.Default.Group, "账号、角色与权限", adminTab = 1),
        NavItem(AppScreen.ADMIN, "公文与审批配置", Icons.Default.Tune, "流转环节与规则", adminTab = 5),
        NavItem(AppScreen.ADMIN, "审计与统计", Icons.Default.History, "会话与文档台账", adminTab = 4),
        NavItem(AppScreen.TRAINING, desc = "语料、样本与数据集"),
    )

    /** 工作区侧栏分组：核心生产力不进侧栏（HOME 四张卡已是入口），避免重复 */
    val groups: List<NavGroup> = listOf(
        NavGroup("dept", "科室空间", "本科室 Agent 与知识", departmentItems),
        NavGroup("business", "业务能力", "资料、流转与归档", businessItems),
        NavGroup("admin", "管理能力", "仅在权限范围内可见", adminItems),
    )

    /** 全局导航抽屉分组：含核心生产力（HOME 四大入口的快捷跳转） */
    val drawerGroups: List<NavGroup> = listOf(
        NavGroup("core", "核心生产力", "日常公文办公的主入口", coreItems),
    ) + groups

    /** 全局导航搜索用扁平列表 */
    fun flat(): List<NavItem> = groups.flatMap { it.items }

    /** 当前页面所属分组（用于工作区导航高亮） */
    fun groupOf(screen: AppScreen): NavGroup? =
        groups.firstOrNull { g -> g.items.any { it.screen == screen } }

    /** 页面在工作区显示的一级标题（返回所属分组名 + 页面名之外的简洁标题） */
    fun titleOf(screen: AppScreen): String = screen.title
}
