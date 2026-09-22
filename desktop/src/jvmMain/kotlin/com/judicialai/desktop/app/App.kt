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
import com.judicialai.desktop.features.ppt.PptScreen
import com.judicialai.desktop.features.settings.SettingsScreen
import com.judicialai.desktop.features.templates.TemplatesScreen
import com.judicialai.desktop.features.training.TrainingScreen
import com.judicialai.desktop.features.workflow.WorkflowScreen
import com.judicialai.desktop.features.writing.WritingScreen

/** 应用根组件：主题 + 登录门 + 外壳 */
@Composable
fun App() {
    AppTheme {
        if (!AppState.loggedIn) {
            LoginScreen()
            return@AppTheme
        }
        // 非管理员访问管理后台时回退工作台（对应 Web 路由 requiresAdmin 守卫）
        if (AppState.screen == AppScreen.ADMIN && !AppState.isAdmin) {
            AppState.screen = AppScreen.HOME
        }
        AppShell(
            current = AppState.screen,
            username = AppState.displayName,
            userRole = AppState.roleText,
            isAdmin = AppState.isAdmin,
            onNavigate = { AppState.navigate(it.screen, it.adminTab) },
            onHome = { AppState.navigate(AppScreen.HOME) },
            onLogout = { AppState.logout() },
        ) {
            when (AppState.screen) {
                AppScreen.HOME -> HomeScreen()
                AppScreen.DEPARTMENT -> DepartmentScreen()
                AppScreen.WRITING -> WritingScreen()
                AppScreen.TEMPLATES -> TemplatesScreen()
                AppScreen.PPT -> PptScreen()
                AppScreen.FORMAT_CHECK -> FormatCheckScreen()
                AppScreen.KNOWLEDGE -> KnowledgeScreen()
                AppScreen.DOCUMENTS -> DocumentsScreen()
                AppScreen.CHAT -> ChatScreen()
                AppScreen.WORKFLOW -> WorkflowScreen()
                AppScreen.TRAINING -> TrainingScreen()
                AppScreen.ADMIN -> AdminScreen()
                AppScreen.SETTINGS -> SettingsScreen()
            }
        }
    }
}
