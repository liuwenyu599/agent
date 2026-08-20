<template>
  <div class="login-container">
    <el-card class="login-card">
      <template #header><h2>🏛️ 司法智能办公辅助平台 V1.0</h2></template>
      <el-tabs v-model="activeTab">
        <el-tab-pane label="登录" name="login">
          <el-form :model="loginForm" @submit.prevent="handleLogin">
            <el-form-item><el-input v-model="loginForm.username" placeholder="用户名" prefix-icon="User" size="large" /></el-form-item>
            <el-form-item><el-input v-model="loginForm.password" type="password" placeholder="密码" prefix-icon="Lock" size="large" show-password /></el-form-item>
            <el-form-item><el-button type="primary" size="large" @click="handleLogin" :loading="loading" style="width: 100%">登录</el-button></el-form-item>
          </el-form>
        </el-tab-pane>
        <el-tab-pane label="注册" name="register" v-if="!isFirstUser">
          <el-form :model="registerForm" @submit.prevent="handleRegister">
            <el-form-item><el-input v-model="registerForm.username" placeholder="用户名" prefix-icon="User" size="large" /></el-form-item>
            <el-form-item><el-input v-model="registerForm.email" placeholder="邮箱" prefix-icon="Message" size="large" /></el-form-item>
            <el-form-item><el-input v-model="registerForm.password" type="password" placeholder="密码" prefix-icon="Lock" size="large" show-password /></el-form-item>
            <el-form-item><el-input v-model="registerForm.real_name" placeholder="真实姓名" prefix-icon="UserFilled" size="large" /></el-form-item>
            <el-form-item><el-input v-model="registerForm.department" placeholder="部门" prefix-icon="OfficeBuilding" size="large" /></el-form-item>
            <el-form-item><el-button type="success" size="large" @click="handleRegister" :loading="loading" style="width: 100%">注册</el-button></el-form-item>
          </el-form>
        </el-tab-pane>
        <el-tab-pane label="首次注册（系统管理员）" name="first-register" v-if="isFirstUser">
          <el-alert title="系统首次使用" description="当前系统没有用户，请创建系统管理员账号" type="info" :closable="false" style="margin-bottom: 16px" />
          <el-form :model="firstRegisterForm" @submit.prevent="handleFirstRegister">
            <el-form-item><el-input v-model="firstRegisterForm.username" placeholder="用户名" prefix-icon="User" size="large" /></el-form-item>
            <el-form-item><el-input v-model="firstRegisterForm.email" placeholder="邮箱" prefix-icon="Message" size="large" /></el-form-item>
            <el-form-item><el-input v-model="firstRegisterForm.password" type="password" placeholder="密码" prefix-icon="Lock" size="large" show-password /></el-form-item>
            <el-form-item><el-input v-model="firstRegisterForm.real_name" placeholder="真实姓名" prefix-icon="UserFilled" size="large" /></el-form-item>
            <el-form-item><el-input v-model="firstRegisterForm.department" placeholder="部门" prefix-icon="OfficeBuilding" size="large" /></el-form-item>
            <el-form-item><el-button type="danger" size="large" @click="handleFirstRegister" :loading="loading" style="width: 100%">创建系统管理员</el-button></el-form-item>
          </el-form>
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<script setup>
import { reactive, ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import axios from 'axios'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()
const loading = ref(false)
const activeTab = ref('login')
const isFirstUser = ref(false)
const loginForm = reactive({ username: '', password: '' })
const registerForm = reactive({ username: '', email: '', password: '', real_name: '', department: '', role: 'user' })
const firstRegisterForm = reactive({ username: '', email: '', password: '', real_name: '', department: '', role: 'developer' })

onMounted(async () => {
  try { const res = await axios.get('/api/v1/auth/check-first-user'); isFirstUser.value = res.data.is_first; if (isFirstUser.value) activeTab.value = 'first-register'; }
  catch (e) { console.error('检测首次用户失败', e) }
})

async function handleLogin() {
  if (!loginForm.username || !loginForm.password) { ElMessage.warning('请输入用户名和密码'); return; }
  loading.value = true
  try { const res = await axios.post('/api/v1/auth/login', { username: loginForm.username, password: loginForm.password }); authStore.setAuth(res.data.access_token, res.data.user); ElMessage.success('登录成功'); router.push('/dashboard'); }
  catch (err) { ElMessage.error(err.response?.data?.detail || '登录失败') } finally { loading.value = false }
}

async function handleRegister() {
  if (!registerForm.username || !registerForm.password || !registerForm.email) { ElMessage.warning('请填写完整信息'); return; }
  loading.value = true
  try { const res = await axios.post('/api/v1/auth/register', registerForm, { headers: { Authorization: `Bearer ${localStorage.getItem('token') || ''}` } }); authStore.setAuth(res.data.access_token, res.data.user); ElMessage.success('注册成功'); router.push('/dashboard'); }
  catch (err) { ElMessage.error(err.response?.data?.detail || '注册失败') } finally { loading.value = false }
}

async function handleFirstRegister() {
  if (!firstRegisterForm.username || !firstRegisterForm.password || !firstRegisterForm.email) { ElMessage.warning('请填写完整信息'); return; }
  loading.value = true
  try { const res = await axios.post('/api/v1/auth/register-first', firstRegisterForm); authStore.setAuth(res.data.access_token, res.data.user); ElMessage.success('系统管理员创建成功'); isFirstUser.value = false; router.push('/dashboard'); }
  catch (err) { ElMessage.error(err.response?.data?.detail || '注册失败') } finally { loading.value = false }
}
</script>

<style scoped>
.login-container { height: 100vh; display: flex; justify-content: center; align-items: center; background: linear-gradient(135deg, #1a5fb4 0%, #4a90d9 100%); }
.login-card { width: 420px; border-radius: 12px; box-shadow: 0 8px 32px rgba(0,0,0,0.2); }
.login-card h2 { text-align: center; margin: 0; color: #1a5fb4; font-size: 22px; }
</style>