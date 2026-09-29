package com.judicialai.desktop.app

import androidx.compose.runtime.Composable
import com.judicialai.desktop.design.layout.AppShell
import com.judicialai.desktop.design.theme.AppTheme
import com.judicialai.desktop.features.admin.AdminScreen
import com.judicialai.desktop.features.auth.LoginScreen
import com.judicialai.desktop.features.chat.ChatScreen
import com.judicialai.desktop.features.department.DepartmentScreen
import com.judicialai.desktop.features.documents.DocumentsScreen
import com.judicialai.desktop.features.formatcheck.FormatCheckScreen
import com.judicialai.desktop.features.home.HomeScreen
import com.judicialai.desktop.features.knowledge.KnowledgeScreen
import com.judicialai.desktop.features.knowledge.KnowledgeQaScreen
import com.judicialai.desktop.features.ppt.PptScreen
import com.judicialai.desktop.features.settings.SettingsScreen
import com.judicialai.desktop.features.templates.TemplatesScreen
import com.judicialai.desktop.features.workflow.WorkflowScreen
import com.judicialai.desktop.features.writing.WritingScreen

/**
 * 应用根组件：主题 + 登录门 + 外壳。
 * 页面读取走 LocalWindowSession（本窗口自己的导航状态），
 * 多开窗口时各自浏览不同页面互不干扰。
 */
@Composable
fun App() {
    val session = LocalWindowSession.current
    AppTheme {
        if (!AppState.loggedIn) {
            LoginScreen()
            return@AppTheme
        }
        // 非管理员访问管理后台时回退工作台（对应 Web 路由 requiresAdmin 守卫）
        if (session.screen == AppScreen.ADMIN && !AppState.isAdmin) {
            session.screen = AppScreen.HOME
        }
        AppShell(
            current = session.screen,
            username = AppState.displayName,
            userRole = AppState.roleText,
            isAdmin = AppState.isAdmin,
            onNavigate = { AppState.navigate(it.screen, it.adminTab) },
            onHome = { AppState.navigate(AppScreen.HOME) },
            onLogout = { AppState.logout() },
        ) {
            when (session.screen) {
                AppScreen.HOME -> HomeScreen()
                AppScreen.DEPARTMENT -> DepartmentScreen()
                AppScreen.WRITING -> WritingScreen()
                AppScreen.TEMPLATES -> TemplatesScreen()
                AppScreen.PPT -> PptScreen()
                AppScreen.FORMAT_CHECK -> FormatCheckScreen()
                AppScreen.KNOWLEDGE -> KnowledgeScreen()
                AppScreen.KNOWLEDGE_QA -> KnowledgeQaScreen()
                AppScreen.DOCUMENTS -> DocumentsScreen()
                AppScreen.CHAT -> ChatScreen()
                AppScreen.WORKFLOW -> WorkflowScreen()
                AppScreen.ADMIN -> AdminScreen()
                AppScreen.SETTINGS -> SettingsScreen()
            }
        }
    }
}
