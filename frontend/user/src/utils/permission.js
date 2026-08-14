export const hasRole = (role) => { try { return JSON.parse(localStorage.getItem('user') || '{}').role === role } catch { return false } }
export const hasAnyRole = (roles) => { try { return roles.includes(JSON.parse(localStorage.getItem('user') || '{}').role) } catch { return false } }
export const isAdmin = () => hasAnyRole(['developer', 'knowledge_admin', 'admin'])
export const isSuperAdmin = () => hasRole('developer')
