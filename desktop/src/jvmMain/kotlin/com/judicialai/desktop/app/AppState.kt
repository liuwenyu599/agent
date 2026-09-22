package com.judicialai.desktop.app

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.judicialai.desktop.core.network.ApiClient
import com.judicialai.desktop.core.storage.ServerConfig

/**
 * 应用全局状态：当前页面、服务器配置、登录态、当前用户。
 * token 只在 ApiClient 内存中，不落盘；用户信息仅保存展示所需字段。
 */
object AppState {

    var screen by mutableStateOf(AppScreen.HOME)

    /** 普通聊天中识别到写作意图时，跳转到工作台携带的一句话需求 */
    var pendingWritingIntent by mutableStateOf<String?>(null)

    // ---- 导航形态 ----
    /** 全局导航抽屉（点击顶部品牌名打开） */
    var navDrawerOpen by mutableStateOf(false)

    /** 工作区导航是否折叠为图标条 */
    var navCollapsed by mutableStateOf(false)

    /** 工作区导航宽度（可拖拽调节，范围 180–360dp） */
    var navWidth by mutableStateOf(236f)

    /** 个人中心抽屉（右上角入口） */
    var personalCenterOpen by mutableStateOf(false)

    /** 工作区导航是否被固定展开（固定后不随页面切换自动收起） */
    var navPinned by mutableStateOf(true)

    /** 导航搜索词：仅用于过滤导航项，不做任何假数据搜索 */
    var navQuery by mutableStateOf("")

    /** 管理后台直达 Tab（对应 AdminScreen 内 TabRow） */
    var adminTab by mutableStateOf(0)

    /**
     * 历史记录「继续」打开指定文档：从历史页 set，由 DocumentsScreen 消费后置回 null。
     * 只做一次性的跨页参数传递，不把 DocumentsViewModel 提升为全局单例。
     */
    var pendingDocumentId by mutableStateOf<String?>(null)

    /**
     * 管理员重置过密码 → true。后端会在改密前拦截业务接口，
     * 客户端据此引导用户到个人中心「账号安全」修改密码。
     */
    var mustChangePassword by mutableStateOf(false)
        private set

    var serverConfig by mutableStateOf(ServerConfig.load())
        private set

    var loggedIn by mutableStateOf(false)
        private set

    var username by mutableStateOf("")
        private set

    var realName by mutableStateOf("")
        private set

    var role by mutableStateOf("user")
        private set

    /** 所属科室名称（来自 /dashboard/summary 或 /organization/me，未取到时为空，UI 不臆造） */
    var departmentName by mutableStateOf("")
    /** 所属科室代码（后端下发；用于科室空间与检索范围） */
    var departmentCode by mutableStateOf("")
    /** 当前科室 Agent 名称（后端下发，未配置时为空） */
    var agentName by mutableStateOf("")
    /** 当前科室 Agent 简介（后端下发，展示用） */
    var agentIntro by mutableStateOf("")
    /** 本科室推荐任务（后端下发；智能写作入口据此给出本科室常用目标） */
    var deptTasks by mutableStateOf(listOf<String>())
    /** 智能助手配置是否可维护（后端按角色返回，不前端猜测） */
    var canManageDeptAgent by mutableStateOf(false)

    /** 全应用唯一网络入口 */
    val api: ApiClient by lazy { ApiClient({ serverConfig }) }

    /** 对应 Web 端 AppLayout.isAdmin：developer / knowledge_admin / admin */
    val isAdmin: Boolean get() = role in setOf("developer", "knowledge_admin", "admin")

    /** 科室管理员：可维护本科室知识、模板与智能助手业务配置 */
    val isKnowledgeAdmin: Boolean get() = role == "knowledge_admin"

    /** 系统管理员：可管理全部科室与系统级配置 */
    val isDeveloper: Boolean get() = role == "developer" || role == "admin"

    val displayName: String get() = realName.ifBlank { username.ifBlank { "用户" } }

    /** 对应 Web 端角色映射 */
    val roleText: String
        get() = when (role) {
            "developer" -> "系统管理员"
            "knowledge_admin" -> "科室管理员"
            "admin" -> "管理员"
            "user" -> "普通用户"
            else -> role
        }

    fun updateServerConfig(cfg: ServerConfig) {
        serverConfig = cfg
        ServerConfig.save(cfg)
    }

    fun onLoginSuccess(username: String, realName: String, role: String,
                       mustChangePassword: Boolean = false) {
        this.username = username
        this.realName = realName
        this.role = role
        this.mustChangePassword = mustChangePassword
        this.loggedIn = true
        this.screen = AppScreen.HOME
        this.navDrawerOpen = false
        // 管理员重置过密码：自动打开个人中心，由 ViewModel 落到「账号安全」引导改密
        if (mustChangePassword) this.personalCenterOpen = true
    }

    /** 改密成功后清除强制改密标记 */
    fun onPasswordChanged() {
        mustChangePassword = false
    }

    fun logout() {
        api.setToken(null)
        loggedIn = false
        username = ""
        realName = ""
        role = "user"
        mustChangePassword = false
        personalCenterOpen = false
        departmentName = ""
        departmentCode = ""
        agentName = ""
        agentIntro = ""
        deptTasks = emptyList()
        canManageDeptAgent = false
        screen = AppScreen.HOME
        navDrawerOpen = false
    }

    /** 统一导航入口：设置页面 + 管理后台 Tab + 关闭抽屉 */
    fun navigate(screen: AppScreen, adminTab: Int = 0) {
        this.adminTab = adminTab
        this.screen = screen
        this.navDrawerOpen = false
        this.navQuery = ""
    }
}
