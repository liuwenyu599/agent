export const isValidEmail = (email) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)
export const isValidPhone = (phone) => /^1[3-9]\d{9}$/.test(phone)
export const isValidPassword = (pwd) => pwd && pwd.length >= 6
export const isValidUsername = (u) => /^[a-zA-Z0-9_]{3,20}$/.test(u)
export const isEmpty = (v) => {
  if (v === null || v === undefined) return true
  if (typeof v === 'string') return v.trim() === ''
  if (Array.isArray(v)) return v.length === 0
  if (typeof v === 'object') return Object.keys(v).length === 0
  return false
}
