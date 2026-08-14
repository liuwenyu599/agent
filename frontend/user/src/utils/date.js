export function formatDate(d, format = 'datetime') {
  if (!d) return '-'
  const date = new Date(d)
  const options = { datetime: { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }, date: { year: 'numeric', month: '2-digit', day: '2-digit' }, time: { hour: '2-digit', minute: '2-digit', second: '2-digit' }, full: { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' } }
  return date.toLocaleString('zh-CN', options[format] || options.datetime)
}
export function formatRelativeTime(d) {
  if (!d) return '-'
  const diff = new Date() - new Date(d)
  const m = Math.floor(diff / 60000)
  const h = Math.floor(diff / 3600000)
  const days = Math.floor(diff / 86400000)
  if (m < 1) return '刚刚'
  if (m < 60) return `${m}分钟前`
  if (h < 24) return `${h}小时前`
  if (days < 30) return `${days}天前`
  return formatDate(d, 'date')
}
