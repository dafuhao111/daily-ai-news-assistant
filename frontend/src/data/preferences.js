export const topicOptions = [
  'AI 与学习教育', 'AI 与体育', 'AI 与日常生活', 'AI 与工作效率', 'AI 与创作',
  '大模型与研究', 'Agent 与工具', '开源项目', 'AI 工程', '多模态', '行业动态',
]

// Unsaved form defaults only; never stand in for a saved subscription or brief.
export const emptyPreferences = {
  name: '', role: '', email: '', topics: [], keywords: '', excluded: '',
  time: '08:30', timezone: 'Asia/Shanghai', enabled: false,
}
export const splitTerms = (value) => value.split(/[,，、\n]/).map((term) => term.trim()).filter(Boolean)

export function validatePreferences(value, identityOnly = false) {
  const errors = {}
  if (!value.name?.trim() || value.name.trim().length > 80) errors.name = '请填写你的称呼（最多 80 字）。'
  if (value.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.email.trim())) errors.email = '请填写有效的收件邮箱。'
  if (value.enabled && !value.email?.trim()) errors.email = '启用每日推送前请填写收件邮箱。'
  if (identityOnly) return errors
  if (!value.topics?.length || value.topics.some((topic) => !topicOptions.includes(topic))) errors.topics = '请至少选择一个关注话题。'
  if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(value.time)) errors.time = '请选择有效的每日时间。'
  try { new Intl.DateTimeFormat('zh-CN', { timeZone: value.timezone }).format() } catch { errors.timezone = '请选择有效的时区。' }
  for (const field of ['keywords', 'excluded']) {
    const terms = splitTerms(value[field])
    if (terms.length > 20 || terms.some((term) => term.length > 80)) errors[field] = '最多 20 个词，每个最多 80 字。'
    if (new Set(terms.map((term) => term.toLowerCase())).size !== terms.length) errors[field] = '关键词不能重复。'
  }
  return errors
}
