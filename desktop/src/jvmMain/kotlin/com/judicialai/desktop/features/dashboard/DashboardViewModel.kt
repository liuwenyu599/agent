package com.judicialai.desktop.features.dashboard

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.network.Endpoints
import com.judicialai.desktop.core.utils.items
import com.judicialai.desktop.core.utils.int
import com.judicialai.desktop.core.utils.obj
import com.judicialai.desktop.core.utils.str
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

class DashboardViewModel {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    data class TplItem(val id: String, val name: String, val category: String, val description: String)
    data class DocItem(val id: String, val title: String, val time: String, val kbName: String)

    var templates by mutableStateOf(listOf<TplItem>())
        private set
    var recentDocs by mutableStateOf(listOf<DocItem>())
        private set

    init {
        loadTemplates()
        loadRecentDocs()
    }

    /** 常用模板：按 use_count 排序取前 4（与 Web DashboardView 一致） */
    fun loadTemplates() {
        scope.launch {
            when (val r = AppState.api.get(Endpoints.Templates.LIST)) {
                is ApiResult.Ok -> {
                    templates = r.data.items()
                        .sortedByDescending { it["use_count"].int() }
                        .take(4)
                        .map {
                            TplItem(
                                it["id"].str(),
                                it["name"].str(),
                                it["category"].str(),
                                it["description"].str(),
                            )
                        }
                }
                is ApiResult.Err -> Unit
            }
        }
    }

    /** 最近文档：从可访问知识库取已发布文档最新几条（与 Web DashboardView 一致） */
    fun loadRecentDocs() {
        scope.launch {
            val kbRes = AppState.api.get(Endpoints.Knowledge.LIST)
            if (kbRes !is ApiResult.Ok) return@launch
            val docs = mutableListOf<DocItem>()
            for (kb in kbRes.data.items().take(3)) {
                val kbId = kb["id"].str()
                val kbName = kb["name"].str()
                when (val dr = AppState.api.get(
                    Endpoints.Knowledge.documents(kbId),
                    mapOf("page" to "1", "page_size" to "3"),
                )) {
                    is ApiResult.Ok -> dr.data.items().forEach { d ->
                        docs += DocItem(
                            d["id"].str(), d["title"].str(),
                            d["created_at"].str().take(16).replace("T", " "),
                            kbName,
                        )
                    }
                    is ApiResult.Err -> Unit
                }
            }
            recentDocs = docs.take(4)
        }
    }
}

