// 仅格式化配置声明的基础类型，不执行表达式，也不解析条目中的 HTML。
export function formatValue(value, format = 'text') {
  if (value === null || value === undefined || value === '') return '—';
  if (format === 'boolean') return value === true ? '是' : value === false ? '否' : '—';
  if (format === 'number') return typeof value === 'number' ? String(value) : '—';
  if (format === 'tags') return Array.isArray(value) ? value.join(' · ') || '—' : '—';
  return ['string', 'number', 'boolean'].includes(typeof value) ? String(value) : '—';
}
