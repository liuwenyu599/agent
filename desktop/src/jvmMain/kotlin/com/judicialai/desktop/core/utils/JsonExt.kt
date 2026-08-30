package com.judicialai.desktop.core.utils

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull

/** 宽松 JSON 读取：后端字段变动时不崩，只取需要的字段 */
fun JsonElement?.obj(): JsonObject? = this as? JsonObject
fun JsonElement?.arr(): List<JsonElement> = (this as? JsonArray)?.toList() ?: emptyList()
fun JsonElement?.str(): String = (this as? JsonPrimitive)?.contentOrNull ?: ""
fun JsonElement?.int(): Int = (this as? JsonPrimitive)?.intOrNull ?: 0
fun JsonElement?.bool(): Boolean = (this as? JsonPrimitive)?.booleanOrNull ?: false

/**
 * 列表接口统一取数组：后端不同模块结构不一，按真实返回依次兼容：
 * - 纯数组（/chat/sessions、/knowledge/list、/users/）
 * - {"items": [...]}
 * - {"data": [...]}（/format-check/records、/knowledge/documents、/chat/admin/sessions）
 * - {"instances": [...]}（/workflow/instances）
 * - {"templates": [...]}（/workflow/templates）
 * - {"attachments": [...]}（/chat/attachments/upload）
 */
fun JsonElement.items(): List<JsonObject> {
    this.obj()?.let { o ->
        for (key in listOf("items", "data", "instances", "templates", "attachments", "records")) {
            val a = o[key] as? JsonArray
            if (a != null) return a.mapNotNull { it.obj() }
        }
    }
    return this.arr().mapNotNull { it.obj() }
}

