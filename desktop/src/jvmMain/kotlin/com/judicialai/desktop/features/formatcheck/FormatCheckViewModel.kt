package com.judicialai.desktop.features.formatcheck

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.utils.arr
import com.judicialai.desktop.core.utils.obj
import com.judicialai.desktop.core.utils.str
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import java.io.File

class FormatCheckViewModel(private val repo: FormatCheckRepository) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    var records by mutableStateOf(listOf<JsonObject>())
        private set
    var current by mutableStateOf<JsonObject?>(null)
        private set
    var issues by mutableStateOf(listOf<JsonObject>())
        private set
    var accepted by mutableStateOf(setOf<Int>())
    var useAi by mutableStateOf(true)
    var status by mutableStateOf<String?>(null)
    var busy by mutableStateOf(false)
        private set

    fun loadRecords() {
        scope.launch {
            when (val r = repo.records()) {
                is ApiResult.Ok -> records = r.data
                is ApiResult.Err -> status = r.message
            }
        }
    }

    fun check(file: File) {
        busy = true
        status = "校验中，请稍候…"
        scope.launch {
            when (val r = repo.check(file, useAi)) {
                is ApiResult.Ok -> {
                    status = "校验完成"
                    loadRecords()
                    r.data.obj()?.let { openRecord(it) }
                }
                is ApiResult.Err -> status = r.message
            }
            busy = false
        }
    }

    fun openRecord(rec: JsonObject) {
        current = rec
        issues = emptyList()
        scope.launch {
            when (val r = repo.paragraphs(rec["id"].str())) {
                is ApiResult.Ok -> {
                    issues = r.data.flatMap { p ->
                        val list = p["issues"].arr().mapNotNull { it.obj() }
                        if (list.isNotEmpty()) list else listOf(p)
                    }.filter { it["type"].str().isNotBlank() || it["message"].str().isNotBlank() }
                    accepted = issues.indices.toSet()
                }
                is ApiResult.Err -> status = r.message
            }
            if (issues.isEmpty()) {
                issues = rec["issues"].arr().mapNotNull { it.obj() }
                accepted = issues.indices.toSet()
            }
        }
    }

    fun fix(target: File) {
        val recId = current?.get("id")?.str() ?: return
        busy = true
        status = "生成修正稿…"
        scope.launch {
            status = when (val r = repo.fix(recId, accepted.toList(), target)) {
                is ApiResult.Ok -> r.data
                is ApiResult.Err -> r.message
            }
            busy = false
        }
    }
}

