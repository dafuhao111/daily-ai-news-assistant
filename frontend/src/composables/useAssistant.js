import { computed, onMounted, onScopeDispose, ref } from 'vue'
import { api } from '../api'
import { emptyPreferences, splitTerms, validatePreferences } from '../data/preferences'

export function useAssistant() {
  const preferences = ref(structuredClone(emptyPreferences))
  const profileConfigured = ref(false)
  const preferencesConfigured = ref(false)
  const mailStatus = ref('unconfigured')
  const mailBusy = ref(false)
  const currentBrief = ref(null)
  const budget = ref(null)
  const status = ref({ latest_run: null, active_run: null, scheduler_running: false, smtp_configured: false, next_run_at: null })
  const now = ref(Date.now())
  const loading = ref(true)
  const ready = ref(false)
  const error = ref('')
  const notice = ref('')
  const actionError = ref('')
  const starting = ref(false)
  const saving = ref(false)
  const running = computed(() => starting.value || !!status.value.active_run)
  let disposed = false
  let initialized = false
  let refreshVersion = 0
  let pollTimer
  let pendingKey = null
  try { pendingKey = sessionStorage.getItem('daily-ai-pending-run') } catch { /* storage is optional */ }
  function setKey(value) {
    pendingKey = value
    try { value ? sessionStorage.setItem('daily-ai-pending-run', value) : sessionStorage.removeItem('daily-ai-pending-run') } catch { /* API remains usable without browser storage */ }
  }
  function applyProfile(profile) {
    preferences.value = { ...preferences.value, name: profile.display_name, role: profile.role || '', email: profile.recipient_email || '' }
    profileConfigured.value = true
    mailStatus.value = profile.mail_test_status
  }
  function applyPreferences(value) {
    preferences.value = { ...preferences.value, topics: value.topics, keywords: value.keywords.join(', '), excluded: value.excluded_keywords.join(', '), time: value.run_time.slice(0, 5), timezone: value.timezone, enabled: value.enabled }
    preferencesConfigured.value = true
  }
  async function optional(path) {
    try { return await api(path) } catch (failure) { if (failure.status === 404) return null; throw failure }
  }
  async function refresh() {
    const version = ++refreshVersion
    const [workspace, brief, allowance] = await Promise.all([api('/status'), api('/briefs/latest'), api('/budget')])
    if (disposed || version !== refreshVersion) return
    status.value = workspace
    currentBrief.value = brief
    budget.value = allowance
    now.value = Date.now()
  }
  async function initialize() {
    if (initialized) {
      try { await refresh(); error.value = '' } catch (failure) { error.value = failure.message }
      return
    }
    loading.value = true
    error.value = ''
    try {
      const [profile, savedPreferences] = await Promise.all([optional('/profile'), optional('/preferences'), refresh()])
      if (disposed) return
      if (profile) applyProfile(profile)
      if (savedPreferences) applyPreferences(savedPreferences)
      initialized = true
      ready.value = true
    } catch (failure) { if (!disposed) error.value = failure.message }
    finally { if (!disposed) loading.value = false }
  }
  async function poll() {
    try {
      if (!initialized) await initialize()
      else { await refresh(); error.value = '' }
    } catch (failure) { if (!disposed) error.value = failure.message }
    if (!disposed) pollTimer = setTimeout(poll, running.value || ['pending', 'sending'].includes(currentBrief.value?.delivery?.status) ? 2000 : 10000)
  }
  async function saveIdentity(value) {
    const errors = validatePreferences(value, true)
    if (Object.keys(errors).length) return { ok: false, errors }
    try {
      applyProfile(await api('/profile', { method: 'PUT', body: { display_name: value.name.trim(), role: value.role.trim() || null, recipient_email: value.email.trim() || null } }))
      return { ok: true, errors: {} }
    } catch (failure) { return { ok: false, errors: { server: failure.message } } }
  }
  async function savePreferences(value) {
    const errors = validatePreferences(value)
    if (Object.keys(errors).length) return { ok: false, errors }
    saving.value = true
    try {
      const identity = await saveIdentity(value)
      if (!identity.ok) return identity
      try {
        applyPreferences(await api('/preferences', { method: 'PUT', body: { topics: value.topics, keywords: splitTerms(value.keywords), excluded_keywords: splitTerms(value.excluded), run_time: value.time, timezone: value.timezone, enabled: value.enabled } }))
      } catch (failure) { return { ok: false, errors: { server: `个人资料已保存；订阅偏好保存失败。${failure.message}` } } }
      notice.value = '个人资料与订阅偏好已保存到数据库。'
      await refresh().catch((failure) => { error.value = failure.message })
      return { ok: true, errors: {} }
    } finally { saving.value = false }
  }
  async function perform(action) {
    actionError.value = ''; notice.value = ''
    try { await action() } catch (failure) { actionError.value = failure.message }
  }
  async function run() {
    if (running.value || mailBusy.value || saving.value) return
    starting.value = true
    await perform(async () => {
      if (!pendingKey) setKey(crypto.randomUUID())
      const accepted = await api('/runs', { method: 'POST', body: {}, key: pendingKey })
      setKey(null)
      await refresh()
      notice.value = ['completed', 'empty'].includes(accepted.status)
        ? '今天已有完成的任务，已读取保存结果，未重复生成或发送。'
        : '任务已提交，页面将自动更新后端执行状态。'
    })
    starting.value = false
  }
  async function mailAction(path, message) {
    if (mailBusy.value || running.value || saving.value) return
    mailBusy.value = true
    await perform(async () => {
      const result = await api(path, { method: 'POST', body: {}, timeout: 45000 })
      mailStatus.value = result.status
      notice.value = result.status === 'failed' ? '测试邮件发送失败，请检查本地 SMTP 配置后重试。' : message
    })
    mailBusy.value = false
  }
  const testEmail = () => mailAction('/mail/test', '邮件已提交给 SMTP。请检查收件箱和垃圾邮件，实际收到后点击确认。')
  const confirmEmail = () => mailAction('/mail/test/confirm', '已记录你确认收到测试邮件。')
  async function retryDelivery(briefId) {
    if (mailBusy.value || running.value) return
    mailBusy.value = true
    await perform(async () => {
      await api(`/briefs/${briefId}/delivery/retry`, { method: 'POST', body: {} })
      await refresh()
      notice.value = '已提交投递重试，复用已保存的简报。'
    })
    mailBusy.value = false
  }
  onMounted(async () => { await initialize(); if (!disposed) pollTimer = setTimeout(poll, running.value ? 2000 : 10000) })
  onScopeDispose(() => { disposed = true; clearTimeout(pollTimer) })
  return { preferences, profileConfigured, preferencesConfigured, mailStatus, mailBusy, currentBrief, budget, status, now, loading, ready, error, notice, actionError, running, saving, initialize, refresh, saveIdentity, savePreferences, run, testEmail, confirmEmail, retryDelivery }
}
