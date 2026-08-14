import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useServerStore = defineStore('server', () => {
  // 从本地存储读取服务器地址
  const serverUrl = ref(localStorage.getItem('server_url') || 'http://localhost:8000')
  
  function setServer(url) {
    serverUrl.value = url.replace(/\/$/, '') // 去掉末尾斜杠
    localStorage.setItem('server_url', serverUrl.value)
  }
  
  return { serverUrl, setServer }
})
