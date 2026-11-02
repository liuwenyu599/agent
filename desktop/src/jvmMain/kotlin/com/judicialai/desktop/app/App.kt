package com.judicialai.desktop.app

import androidx.compose.runtime.Composable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.runtime.CompositionLocalProvider
import com.judicialai.desktop.design.layout.AppShell
import com.judicialai.desktop.design.theme.AppTheme
import com.judicialai.desktop.design.components.ToastHost
import com.judicialai.desktop.design.components.ToastState
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.unit.dp
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

val LocalToastState = staticCompositionLocalOf<ToastState> { ToastState() }

/**
 * 应用根组件：主题 + 登录门 + 外壳。
 * 页面读取走 LocalWindowSession（本窗口自己的导航状态），
 * 多开窗口时各自浏览不同页面互不干扰。
 */
@Composable
fun App() {
    val session = LocalWindowSession.current
    CompositionLocalProvider(LocalToastState provides session.toastState) {
        AppTheme {
            // 注意：这里绝不能包 SelectionContainer——下拉菜单/对话框在桌面上
            // 是独立窗口层级，其内部文本一旦可被框选就会抛
            // "layouts are not part of the same hierarchy"（CMP-7112）。
            // 框选复制只放在需要它的正文区域（WritingScreen）内部。
            Box(Modifier.fillMaxSize()) {
                    if (!AppState.loggedIn) {
                        LoginScreen()
                    } else {
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
                    ToastHost(
                        session.toastState,
                        Modifier.align(Alignment.TopEnd).padding(16.dp).widthIn(max = 420.dp),
                    )
            }
        }
    }
}
