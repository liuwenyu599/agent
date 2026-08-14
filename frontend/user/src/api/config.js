import axios from 'axios'

export function createApi() {
  const api = axios.create({
    baseURL: '/api/v1',
    timeout: 30000
  })

  // 请求拦截器：添加 token
  api.interceptors.request.use(config => {
    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  })

  // 响应拦截器：处理 401
  api.interceptors.response.use(
    response => response,
    error => {
      if (error.response?.status === 401) {
        // Token 过期，清除登录状态并跳转
        localStorage.removeItem('token')
        localStorage.removeItem('user')
        window.location.href = '/login'
      }
      return Promise.reject(error)
    }
  )

  return api
}
