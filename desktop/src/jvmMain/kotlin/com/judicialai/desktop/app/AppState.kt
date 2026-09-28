package com.judicialai.desktop.app

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.judicialai.desktop.core.network.ApiClient
import com.judicialai.desktop.core.storage.ServerConfig
import com.judicialai.desktop.features.ppt.PptJobEngine

/**
 * 模板中心「使用模板」→ 智能写作工作台 的一次性参数。
 * 由 TemplatesViewModel 组装（模板绑定 + 要素指令），WritingScreen 消费后置回 null。
 */
data class AppGuideStep(
    val screen: AppScreen,
    val title: String,
    val description: String,
    val actionHint: String,
)

data class PendingTemplateWrite(
    val templateId: String,
    val templateName: String,
    val docType: String,
    val title: String,
    val message: String,
)

/**
 * 应用全局状态：服务器配置、登录态、当前用户、跨页面生成任务标记。
 * token 只在 ApiClient 内存中，不落盘；用户信息仅保存展示所需字段。
 *
 * 多窗口：页面 / 导航抽屉 / 个人中心是「每个窗口一份」的状态（见 WindowSession），
 * 这里的 screen / navDrawerOpen / personalCenterOpen 是路由到「当前焦点窗口」的便捷入口，
 * 供.navigate()、登录、菜单点击等交互使用（交互必然发生在焦点窗口）。
 * 生成任务标记（pptOutlineGenerating / writingGenerating 等）仍然是全局共享的：
 * 一个窗口里跑生成，另一个窗口能看到进度，切回不丢任务不报错。
 */
object AppState {

    /** 使用指南：从个人中心启动，按步骤跳转页面并显示导览提示。 */
    val guideSteps: List<AppGuideStep> = listOf(
        AppGuideStep(AppScreen.HOME, "工作台", "从这里进入最常用的办公能力。", "直接选择要完成的任务，按页面提示继续即可。"),
        AppGuideStep(AppScreen.WRITING, "智能写作", "描述任务、补充材料并生成正式文稿。", "先说清楚要写什么，再确认结构和内容。"),
        AppGuideStep(AppScreen.TEMPLATES, "模板中心", "查找系统、科室和个人常用模板。", "选择模板后填写必要要素，再进入智能写作。"),
        AppGuideStep(AppScreen.PPT, "PPT 助手", "从主题、材料或知识库生成汇报演示文稿。", "先生成并确认大纲，再进入视觉设计和导出。"),
        AppGuideStep(AppScreen.FORMAT_CHECK, "格式校验", "检查公文格式与常见规范问题。", "上传或选择文档后执行检查，再逐项处理问题。"),
        AppGuideStep(AppScreen.DEPARTMENT, "科室空间", "查看本科室常用业务、知识资源、模板和工作流程。", "日常办理本科室业务时，可从这里快速进入对应资源。"),
        AppGuideStep(AppScreen.KNOWLEDGE, "知识库", "查找和维护可用于写作与问答的业务资料。", "先选择知识库，再检索或查看其中的资料。"),
        AppGuideStep(AppScreen.WORKFLOW, "工作流程", "按固定业务步骤连续生成和整理多份材料。", "选择流程模板后逐节点完成内容，必要时可调整步骤。"),
        AppGuideStep(AppScreen.CHAT, "历史记录", "查看以前生成的对话、文档、PPT 和工作流程。", "需要继续以前的工作时，从这里找到记录并打开。"),
        AppGuideStep(AppScreen.DOCUMENTS, "我的文档", "集中查看和继续编辑已保存的文档。", "打开文档后可查看版本、继续编辑或导出。"),
    )
    var guideActive by mutableStateOf(false)
        private set
    var guideIndex by mutableStateOf(0)
        private set
    val currentGuideStep: AppGuideStep?
        get() = guideSteps.getOrNull(guideIndex)

    fun startGuide(screen: AppScreen? = null) {
        guideIndex = screen?.let { target ->
            guideSteps.indexOfFirst { it.screen == target }.takeIf { it >= 0 }
        } ?: 0
        guideActive = true
        personalCenterOpen = false
        currentGuideStep?.let { navigate(it.screen) }
    }

    fun nextGuideStep() {
        if (!guideActive) return
        if (guideIndex >= guideSteps.lastIndex) {
            stopGuide()
            return
        }
        guideIndex += 1
        currentGuideStep?.let { navigate(it.screen) }
    }

    fun previousGuideStep() {
        if (!guideActive || guideIndex <= 0) return
        guideIndex -= 1
        currentGuideStep?.let { navigate(it.screen) }
    }

    fun stopGuide() {
        guideActive = false
        guideIndex = 0
    }

    /** 当前焦点窗口的页面（多窗口各自独立导航） */
    var screen: AppScreen
        get() = (WindowManager.active ?: WindowManager.ensureMain()).screen
        set(value) { (WindowManager.active ?: WindowManager.ensureMain()).screen = value }

    /** 普通聊天中识别到写作意图时，跳转到工作台携带的一句话需求 */
    var pendingWritingIntent by mutableStateOf<String?>(null)

    /** 模板中心填好要素后点「生成」：跳转智能写作工作台并携带模板与组装好的指令 */
    var pendingWritingTemplate by mutableStateOf<PendingTemplateWrite?>(null)

    /**
     * 写作工作台「返回模板重新填写」：携带模板 id 跳回模板中心，
     * 由 TemplatesScreen 消费（选中该模板并打开填表面板）后置回 null。
     */
    var pendingTemplateUseId by mutableStateOf<String?>(null)

    /** 最近一次模板要素填写值（「返回模板重新填写」时预填，避免重打） */
    var lastTemplateUseId by mutableStateOf<String?>(null)
    var lastTemplateUseValues by mutableStateOf<Map<String, String>>(emptyMap())

    // ---- 导航形态（按窗口路由到焦点窗口的会话） ----
    /** 全局导航抽屉（点击顶部品牌名打开） */
    var navDrawerOpen: Boolean
        get() = (WindowManager.active ?: WindowManager.ensureMain()).navDrawerOpen
        set(value) { (WindowManager.active ?: WindowManager.ensureMain()).navDrawerOpen = value }

    /** 工作区导航是否折叠为图标条 */
    var navCollapsed by mutableStateOf(false)

    /** 工作区导航宽度（可拖拽调节，范围 180–360dp） */
    var navWidth by mutableStateOf(236f)

    /** 个人中心抽屉（右上角入口） */
    var personalCenterOpen: Boolean
        get() = (WindowManager.active ?: WindowManager.ensureMain()).personalCenterOpen
        set(value) { (WindowManager.active ?: WindowManager.ensureMain()).personalCenterOpen = value }

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
     * PPT 工作台「当前文档 id」（跨页面恢复用）。
     * 由 PptViewModel 在拿到服务端 doc_id 时写入（applyOutline：大纲生成 / 导入 / 打开已有文档）；
     * PptScreen 重建（切到别的页面再切回时 remember 会重建 ViewModel，本地状态清零）时消费：
     * 本地 docId 为空则按此 id 调 openDocument，从服务端取回大纲并回到工作台。
     * **不在消费后清空**（否则切走再切回仍然会丢），仅在用户显式回到入口页
     * （PptViewModel.backToEntry）、删除该文档或登出时置 null。
     */
    var pendingPptDocId by mutableStateOf<String?>(null)

    /**
     * PPT 大纲是否正在生成中（全局可见，不随页面切换丢失）。
     * 由 PptViewModel.startOutline 开始时置 true，结束（成功/失败）置 false。
     * 页面切换不会取消生成协程（ViewModel 使用独立 CoroutineScope 且没有 onCleared），
     * 所以切回来时可能正卡在「还没拿到 doc_id」这一段：PptScreen 据此显示明确的
     * 「正在生成中」提示而不是空白入口页；生成完成后由仍在运行的协程写入
     * [pendingPptDocId]，界面随即自动恢复到工作台。
     */
    var pptOutlineGenerating by mutableStateOf(false)

    /**
     * PPT 是否正在导出 pptx（跨页面可见）。
     * 由 PptViewModel.generateAndExport 开始时置 true、结束（成功/失败）置 false。
     * 用途同 [pptOutlineGenerating]：切走再切回会得到新的 ViewModel（busy 已重置），
     * 仅靠 busy 挡不住重复发起，而两次导出会写同一个文件，必须用全局标记挡住。
     */
    var pptExporting by mutableStateOf(false)

    /**
     * 上一次 PPT 生成 / 导出的失败原因（跨页面可见）。
     * 由 PptViewModel 在生成失败时写入真实的服务端或解析错误信息，成功时置 null。
     * PptScreen 消费：切到别的页面再切回时本地 ViewModel 已被重建、status 丢失，
     * 只有这里还能告诉用户「上次生成失败了，为什么」。
     * 清空时机同 [pendingPptDocId]：回到入口页（backToEntry）、登出，
     * 以及用户在提示条上点「知道了」（停在入口页时没有别的可清除入口）。
     */
    var pptLastError by mutableStateOf<String?>(null)

    /**
     * PPT 异步生成任务号（跨页面恢复用，对应后端 POST /ppt/jobs 返回的 job_id）。
     * 由 features.ppt.PptJobEngine 在提交成功时写入、任务终态时按情况保留或清空：
     * - 生成中（SUBMITTED/GENERATING）：切走再切回时据此重新挂上轮询，进度不丢；
     * - 成功并落盘后：保留到用户「返回编辑」（reset）为止，切回来还能看到缩略图与下载按钮；
     * - 失败 / 取消 / 退出登录 / 提交新任务：清空。
     * 任务进度本身挂在 PptJobEngine（全局），这里只放「去哪儿找这个任务」的句柄。
     */
    var pendingPptJobId by mutableStateOf<String?>(null)

    /**
     * PPT 是否有一个异步生成任务占着工作台（跨页面可见）。
     * 用途同 [pptOutlineGenerating]：切回页面时据此直接展示生成工作台而不是空的入口页。
     */
    var pptJobActive by mutableStateOf(false)

    /**
     * 智能写作「当前任务 id」（跨页面恢复用）。
     * 由 WritingViewModel.applyResponse 在拿到后端 task_id 时写入；
     * WritingScreen 重建时消费：本地尚无任务则按此 id 调 GET /writing/tasks/{id} 恢复
     * 任务上下文、正文与版本号。仅在用户「重新描述任务」/ 新建任务（newTask）或登出时置 null。
     */
    var pendingWritingTaskId by mutableStateOf<String?>(null)

    /**
     * 智能写作是否有生成请求在跑（全局可见；创建任务 / 起草 / 修改 / 对话均计入）。
     * 由 WritingViewModel 各生成入口在开始时置 true、结束（成功/失败/取消）置 false。
     * 用途同 [pptOutlineGenerating]：切回页面时给出「正在处理」的明确提示；
     * 并在其由 true 变为 false 时用服务端最新状态刷新一次——生成可能是在离开页面之后
     * 才由仍在运行的协程跑完的，本地拿到的还是生成前的内容。
     */
    var writingGenerating by mutableStateOf(false)

    /**
     * 上一次智能写作生成 / 修改的失败原因（跨页面可见）。
     * 由 WritingViewModel 各生成入口在开始时置 null、失败（fail）时写入真实错误信息。
     * WritingScreen 消费：切走再切回时即便靠 openTask 恢复出了任务，恢复到的也是
     * 生成前的状态（可能是空正文），必须明确告知失败原因，否则用户只看到「没有正文」。
     * 清空时机同 [pendingWritingTaskId]：新建任务（newTask）、登出，
     * 以及用户在提示条上点「知道了」。
     */
    var writingLastError by mutableStateOf<String?>(null)

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
        // 服务器地址一旦变化，当前 token 绝不能继续复用到新地址。
        // 否则用户在已登录状态修改 baseUrl 后，下一次请求可能把原服务器的
        // Bearer token 发给另一个服务器，既会造成鉴权混乱，也存在凭据泄露风险。
        val endpointChanged = serverConfig.baseUrl.trim().trimEnd('/') !=
            cfg.baseUrl.trim().trimEnd('/')
        if (endpointChanged && loggedIn) {
            logout()
        }
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
        // 换账号登录：全局 PPT 任务引擎里若还挂着别人的任务（被动掉线等未走 logout 的路径），
        // 必须在这里按归属账号清掉，否则新账号一打开 PPT 助手就看到上一个账号在「生成中」
        PptJobEngine.dropForeignJob()
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
        stopGuide()
        departmentName = ""
        departmentCode = ""
        agentName = ""
        agentIntro = ""
        deptTasks = emptyList()
        canManageDeptAgent = false
        screen = AppScreen.HOME
        navDrawerOpen = false
        // 跨页面恢复标记一并清空，避免换账号登录后恢复到上一个账号的文档/任务
        pendingPptDocId = null
        pptOutlineGenerating = false
        pptExporting = false
        pptLastError = null
        // 异步生成任务属于上一个账号：句柄要清，任务本身也要从全局引擎里摘掉。
        // PptJobEngine 是全局单例（不随页面销毁），界面读的是它的 current，
        // 只清这里的标记的话，换账号登录打开 PPT 助手仍会看到上一个账号的「生成中」。
        // reset() 内部也会清 pendingPptJobId / pptJobActive，这里保留显式赋值做双保险。
        PptJobEngine.reset()
        pendingPptJobId = null
        pptJobActive = false
        pendingWritingTaskId = null
        writingGenerating = false
        writingLastError = null
    }

    /** 统一导航入口：设置页面 + 管理后台 Tab + 关闭抽屉（作用于焦点窗口） */
    fun navigate(screen: AppScreen, adminTab: Int = 0) {
        this.adminTab = adminTab
        this.screen = screen
        this.navDrawerOpen = false
        this.navQuery = ""
    }
}
