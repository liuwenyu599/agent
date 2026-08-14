import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'
import { useRouter } from 'vue-router'

const API_URL = '/api/v1'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('token') || '')
  const user = ref(null)
  
  // 安全解析 user
  try {
    const userStr = localStorage.getItem('user')
    if (userStr && userStr !== 'null' && userStr !== 'undefined') {
      user.value = JSON.parse(userStr)
    }
  } catch (e) {
    user.value = null
    localStorage.removeItem('user')
  }

  const isLoggedIn = computed(() => !!token.value && !!user.value)
  const isAdmin = computed(() => {
    const role = user.value?.role
    return ['knowledge_admin', 'developer', 'admin'].includes(role)
  })

  function setAuth(newToken, newUser) {
    token.value = newToken
    user.value = newUser
    localStorage.setItem('token', newToken)
    localStorage.setItem('user', JSON.stringify(newUser))
    axios.defaults.headers.common['Authorization'] = `Bearer ${newToken}`
  }

  function clearAuth() {
    token.value = ''
    user.value = null
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    delete axios.defaults.headers.common['Authorization']
    // 强制刷新页面，确保所有状态清空
    window.location.href = '/login'
  }

  if (token.value) {
    axios.defaults.headers.common['Authorization'] = `Bearer ${token.value}`
  }

  return { token, user, isLoggedIn, isAdmin, setAuth, clearAuth }
})
