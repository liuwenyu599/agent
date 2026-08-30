package com.judicialai.desktop.app

import androidx.compose.runtime.Composable
import com.judicialai.desktop.design.layout.AppShell
import com.judicialai.desktop.design.theme.AppTheme
import com.judicialai.desktop.features.admin.AdminScreen
import com.judicialai.desktop.features.auth.LoginScreen
import com.judicialai.desktop.features.chat.ChatScreen
import com.judicialai.desktop.features.dashboard.DashboardScreen
import com.judicialai.desktop.features.formatcheck.FormatCheckScreen
import com.judicialai.desktop.features.knowledge.KnowledgeScreen
import com.judicialai.desktop.features.ppt.PptScreen
import com.judicialai.desktop.features.settings.SettingsScreen
import com.judicialai.desktop.features.templates.TemplatesScreen
import com.judicialai.desktop.features.workflow.WorkflowScreen

/** 应用根组件：主题 + 登录门 + 外壳 */
@Composable
fun App() {
    AppTheme {
        if (!AppState.loggedIn) {
            LoginScreen()
            return@AppTheme
        }
        // 非管理员访问管理后台时回退首页（对应 Web 路由 requiresAdmin 守卫）
        if (AppState.screen == AppScreen.ADMIN && !AppState.isAdmin) {
            AppState.screen = AppScreen.DASHBOARD
        }
        AppShell(
            current = AppState.screen,
            username = AppState.displayName,
            userRole = AppState.roleText,
            isAdmin = AppState.isAdmin,
            onNavigate = { AppState.screen = it },
            onLogout = { AppState.logout() },
        ) {
            when (AppState.screen) {
                AppScreen.DASHBOARD -> DashboardScreen()
                AppScreen.CHAT -> ChatScreen()
                AppScreen.KNOWLEDGE -> KnowledgeScreen()
                AppScreen.TEMPLATES -> TemplatesScreen()
                AppScreen.FORMAT_CHECK -> FormatCheckScreen()
                AppScreen.PPT -> PptScreen()
                AppScreen.WORKFLOW -> WorkflowScreen()
                AppScreen.ADMIN -> AdminScreen()
                AppScreen.SETTINGS -> SettingsScreen()
            }
        }
    }
}

