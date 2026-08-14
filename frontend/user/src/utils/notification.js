import { ElMessage, ElNotification, ElMessageBox } from 'element-plus'
export const success = (msg) => ElMessage.success(msg)
export const error = (msg) => ElMessage.error(msg)
export const warning = (msg) => ElMessage.warning(msg)
export const info = (msg) => ElMessage.info(msg)
export const notify = (title, msg, type = 'info') => ElNotification({ title, message: msg, type, duration: 3000 })
export const confirm = async (title, msg, type = 'warning') => { try { await ElMessageBox.confirm(msg, title, { type }); return true } catch { return false } }
export const prompt = async (title, msg, defaultValue = '') => { try { const v = await ElMessageBox.prompt(msg, title, { confirmButtonText: '确定', cancelButtonText: '取消', inputValue: defaultValue }); return v.value } catch { return null } }
