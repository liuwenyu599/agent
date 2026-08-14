import { createApi } from './config.js'

const api = createApi()

export const login = (data) => api.post('/auth/login', data)
export const register = (data) => api.post('/auth/register', data)
export const registerFirst = (data) => api.post('/auth/register-first', data)
export const checkFirstUser = () => api.get('/auth/check-first-user')
export const getMe = () => api.get('/auth/me')
