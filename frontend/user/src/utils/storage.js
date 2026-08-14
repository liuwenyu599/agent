export const setItem = (key, value) => { try { localStorage.setItem(key, JSON.stringify(value)) } catch (e) { console.error(e) } }
export const getItem = (key, d = null) => { try { const v = localStorage.getItem(key); if (v === null || v === 'null' || v === 'undefined') return d; return JSON.parse(v) } catch (e) { return d } }
export const removeItem = (key) => localStorage.removeItem(key)
export const clearAll = () => localStorage.clear()
