package com.judicialai.desktop.features.writing

import kotlinx.serialization.json.JsonObject

/**
 * 一次写作任务的工作台配置（WorkspaceSpec）。
 *
 * 由后端 /writing/tasks/plan 依据用户的一句话指令生成：
 * AI 不只写正文，还负责构造「这一次写作所需的工作环境」——
 * 文种、报送对象、参考材料、知识范围、模板、左栏分区、AI 动作，全部随任务变化。
 *
 * 前端不做任何本地推导：spec 为空时不进入工作台，左栏回退到后端 task_context 字段面板。
 */
data class WorkspaceSpec(
    /** 文种，如「工作情况报告」「会议纪要」「通知」 */
    val docType: String = "",
    /** 写作目标（一句话） */
    val target: String = "",
    /** 报送 / 主送对象 */
    val audience: String = "",
    /** 所属科室 */
    val department: String = "",
    /** 承担本次写作的科室 Agent */
    val agent: String = "",
    /** 建议标题 */
    val title: String = "",
    /** 规划来源：llm = 模型规划，rule = 规则降级（后端会在响应中标注） */
    val source: String = "",
    /** 服务端已经完成语义解析的任务上下文；创建任务时原样复用，避免再跑一次 LLM。 */
    val plannedContext: JsonObject? = null,
    /** 已解析出的任务要素（键：值） */
    val fields: List<SpecField> = emptyList(),
    /** 参考材料（可勾选） */
    val materials: List<SpecOption> = emptyList(),
    /** 知识来源（可切换，后端已按权限过滤后的可选项） */
    val knowledge: List<SpecOption> = emptyList(),
    /** 推荐模板 */
    val templateId: String = "",
    val templateName: String = "",
    /**
     * 可选的文种模板（模板中心）。**默认不选**——不选时后端不注入任何模板要求，
     * 模型按其自身判断组织文种与结构；选了才在该文种的专门要求下撰写。
     * 刻意做成可选而非强制：强套模板会让 14B 变得死板。
     */
    val templateOptions: List<SpecOption> = emptyList(),
    /** 后端实际使用的知识范围（allowed_scope） */
    val scopes: List<String> = emptyList(),
    /** 传给后端的知识库 id 列表 */
    val kbIds: List<String> = emptyList(),
    /** AI 动作（右栏快捷操作） */
    val aiActions: List<String> = emptyList(),
)

/** 左栏「本次写作」分区里的要素行 */
data class SpecField(val label: String, val value: String)

/** 可勾选 / 可切换的条目：材料勾选、知识来源开关 */
data class SpecOption(
    val id: String = "",
    val label: String,
    val selected: Boolean = false,
    /** 不可选时的原因（如「无权限」「未匹配到」），为空表示可选 */
    val note: String = "",
)
