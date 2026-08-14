export function debounce(fn, delay = 300) {
  let t = null
  return function (...args) { if (t) clearTimeout(t); t = setTimeout(() => fn.apply(this, args), delay) }
}
export function throttle(fn, interval = 300) {
  let last = 0
  return function (...args) { const now = Date.now(); if (now - last >= interval) { last = now; fn.apply(this, args) } }
}
