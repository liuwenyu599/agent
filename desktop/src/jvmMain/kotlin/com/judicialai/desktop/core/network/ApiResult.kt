package com.judicialai.desktop.core.network

/** 统一请求结果：成功携带数据，失败携带状态码与友好提示（绝不暴露堆栈给 UI） */
sealed class ApiResult<out T> {
    data class Ok<T>(val data: T) : ApiResult<T>()
    data class Err(val status: Int?, val message: String) : ApiResult<Nothing>()
}

