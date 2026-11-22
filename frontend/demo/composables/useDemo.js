import { computed, onScopeDispose, ref } from 'vue'
import { defaults, initialBriefs, makeBrief, makeTrace, STORAGE_KEY, DEMO_DATE, topicOptions } from '../data/demo'
const clone = (value) => JSON.parse(JSON.stringify(value))
const legacyTopicAliases = { '大模型进展': '大模型与研究' }

export function validatePreferences(value) {
  const errors = {}
  if (!value.name?.trim()) errors.name = '请填写你的称呼。'
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.email || '')) errors.email = '请填写有效的收件邮箱。'
  if (!Array.isArray(value.topics) || !value.topics.length) errors.topics = '请至少选择一个关注话题。'
  if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(value.time || '')) errors.time = '请选择有效的每日时间。'
  if (!['Asia/Shanghai', 'America/Los_Angeles', 'UTC'].includes(value.timezone)) errors.timezone = '请选择支持的时区。'
  return errors
}

function readPreferences(storage) {
  try {
    const raw = storage?.getItem(STORAGE_KEY)
    if (!raw) return { preferences: structuredClone(defaults), warning: '' }
    const value = JSON.parse(raw)
    const strings = ['name', 'role', 'email', 'keywords', 'excluded', 'time', 'timezone']
    if (!Array.isArray(value.topics)) throw new Error('invalid topics')
    const topics = [...new Set(value.topics.map((topic) => legacyTopicAliases[topic] || topic))]
    const normalized = { ...value, topics }
    if (strings.some((key) => typeof value[key] !== 'string') || typeof value.enabled !== 'boolean' ||
      Object.keys(validatePreferences(normalized)).length || topics.some((topic) => !topicOptions.includes(topic))) throw new Error('invalid')
    return { preferences: Object.fromEntries(Object.keys(defaults).map((key) => [key, normalized[key]])), warning: '' }
  } catch {
    return { preferences: structuredClone(defaults), warning: '无法读取本地演示偏好，已使用示例配置；可以重新保存。' }
  }
}

export function useDemo(storage) {
  let browserStorage = storage
  if (browserStorage === undefined) {
    try { browserStorage = window.localStorage } catch { browserStorage = null }
  }
  const loaded = readPreferences(browserStorage)
  const preferences = ref(loaded.preferences)
  const notice = ref(loaded.warning)
  const briefs = ref(structuredClone(initialBriefs))
  const running = ref(false)
  const runStatus = ref('idle')
  const trace = ref([])
  const scenario = ref('success')
  const mailStatus = ref('idle')
  const mailBusy = ref(false)
  const timers = new Map()
  let disposed = false
  const currentBrief = computed(() => briefs.value.find((brief) => brief.date === DEMO_DATE))

  function delay(ms) {
    return new Promise((resolve) => {
      const timer = setTimeout(() => { timers.delete(timer); resolve() }, ms)
      timers.set(timer, resolve)
    })
  }
  onScopeDispose(() => {
    disposed = true
    for (const [timer, resolve] of timers) { clearTimeout(timer); resolve() }
    timers.clear()
  })

  function savePreferences(value) {
    const errors = validatePreferences(value)
    if (Object.keys(errors).length) return { ok: false, errors }
    const normalized = { ...clone(value), name: value.name.trim(), email: value.email.trim() }
    try {
      if (!browserStorage) throw new Error('storage unavailable')
      browserStorage.setItem(STORAGE_KEY, JSON.stringify(normalized))
      if (normalized.email !== preferences.value.email) mailStatus.value = 'idle'
      preferences.value = normalized
      notice.value = '模拟偏好已保存到当前浏览器。没有配置真实订阅或发信服务。'
      return { ok: true, errors: {} }
    } catch {
      notice.value = '保存失败：浏览器存储不可用。输入仍保留，请检查浏览器设置后重试。'
      return { ok: false, errors: { storage: notice.value } }
    }
  }

  function setEnabled(enabled) {
    return savePreferences({ ...clone(preferences.value), enabled })
  }

  async function run() {
    if (running.value || mailBusy.value) return
    const selected = scenario.value
    notice.value = ''
    running.value = true
    runStatus.value = 'running'
    trace.value = []
    for (const [index, event] of makeTrace(selected).entries()) {
      await delay(400)
      if (disposed) return
      trace.value.push({ ...event, step: index + 1 })
    }
    const status = ['failure', 'model_failure'].includes(selected) ? 'failed' : selected === 'empty' ? 'empty' : 'ready'
    // Failed runs preserve an already saved brief, as the real product must.
    if (status !== 'failed') {
      const brief = makeBrief(DEMO_DATE, status)
      if (selected === 'mail_failure') brief.delivery = 'failed'
      briefs.value = [brief, ...briefs.value.filter((item) => item.date !== DEMO_DATE)]
    }
    runStatus.value = status === 'failed' ? 'failed' : selected === 'mail_failure' ? 'mail_failed' : status === 'empty' ? 'empty' : 'completed'
    running.value = false
  }

  async function testEmail(fail = false) {
    if (mailBusy.value || running.value) return
    mailBusy.value = true
    mailStatus.value = 'loading'
    await delay(650)
    if (disposed) return
    mailStatus.value = fail ? 'failed' : 'success'
    mailBusy.value = false
  }

  async function retryDelivery() {
    if (mailBusy.value || running.value || currentBrief.value?.delivery !== 'failed') return
    mailBusy.value = true
    await delay(650)
    if (disposed) return
    currentBrief.value.delivery = 'submitted'
    runStatus.value = 'completed'
    notice.value = '模拟重试已完成，简报内容保持不变；未发送真实邮件。'
    trace.value.push({ type: 'system', name: '重试投递（模拟）', detail: '复用已保存简报，模拟服务接受邮件请求，未重新生成。', step: trace.value.length + 1 })
    mailBusy.value = false
  }

  return { preferences, notice, briefs, currentBrief, running, runStatus, trace, scenario, mailStatus, mailBusy, savePreferences, setEnabled, run, testEmail, retryDelivery }
}
