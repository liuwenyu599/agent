package com.judicialai.desktop.features.writing

import com.judicialai.desktop.features.knowledge.KnowledgeRepository
import com.judicialai.desktop.features.knowledge.KnowledgeViewModel

/** 会话级共享 ViewModel 句柄：智能写作工作台跨屏保留任务状态。 */
object WritingSessionHolder {
    var viewModel: WritingViewModel? = null
}
