import { vi } from 'vitest'
export const profile = { display_name: '测试读者', role: '开发者', recipient_email: 'reader@example.org', mail_test_status: 'succeeded', mail_tested_at: null }
export const preferences = { topics: ['Agent 与工具'], keywords: ['Agent'], excluded_keywords: [], run_time: '08:30:00', timezone: 'Asia/Shanghai', enabled: false }
export const form = { name: profile.display_name, role: profile.role, email: profile.recipient_email, topics: preferences.topics, keywords: 'Agent', excluded: '', time: '08:30', timezone: 'Asia/Shanghai', enabled: false }
export const brief = {
  id: 7, run_id: 'run-7', run_status: 'completed', report_date: '2026-11-22', generated_at: '2026-11-22T01:00:00Z', item_count: 1, empty_reason: null,
  items: [{ article_id: 'article-7', title: '测试来源发布 Agent 更新', summary: '模型基于来源的中文概括。', relevance_reason: '符合 Agent 方向。', source_excerpt: 'Original source excerpt.', category: 'AI 工程', source_name: '测试来源', url: 'https://news.example.org/agent', published_at_utc: null, published_at_raw: null, fetched_at_utc: '2026-11-22T00:59:00Z' }],
  delivery: { brief_id: 7, status: 'skipped', last_error_code: 'subscription_disabled', attempt_count: 0 },
}
export const run = { run_id: 'run-7', report_date: '2026-11-22', status: 'completed', started_at: '2026-11-22T00:58:00', finished_at: '2026-11-22T01:00:00', error_code: null }
const clone = (value) => JSON.parse(JSON.stringify(value))
export function mockApi(overrides = {}) {
  const state = { profile: clone(profile), preferences: clone(preferences), brief: clone(brief), status: { profile_configured: true, preferences_configured: true, smtp_configured: true, scheduler_running: false, next_run_at: null, active_run: null, latest_run: clone(run) }, history: [{ ...clone(run), brief_id: 7, item_count: 1, delivery: clone(brief.delivery) }], ...overrides }
  const reply = (data, status = 200) => ({ ok: status < 400, status, json: async () => clone(data) })
  const fetcher = vi.fn(async (url, options = {}) => {
    const parsed = new URL(url, 'http://localhost')
    const path = parsed.pathname.replace('/api/v1', '')
    const method = options.method || 'GET'
    if (state.failure) throw new TypeError('network failed')
    if (state.reject?.(path, method)) return reply({ detail: state.rejectCode || 'database_unavailable' }, 503)
    if (path === '/profile') {
      if (method === 'PUT') {
        const body = JSON.parse(options.body)
        state.profile = { ...state.profile, ...body, mail_test_status: body.recipient_email === state.profile?.recipient_email ? state.profile.mail_test_status : 'unconfigured' }
      }
      return state.profile ? reply(state.profile) : reply({ detail: 'profile_not_configured' }, 404)
    }
    if (path === '/preferences') {
      if (method === 'PUT') state.preferences = JSON.parse(options.body)
      return state.preferences ? reply(state.preferences) : reply({ detail: 'preferences_not_configured' }, 404)
    }
    if (path === '/budget') return reply(state.budget || { initialized: true, limit_tokens: 1000000, confirmed_tokens: 118771, uncertain_tokens: 200000, reserved_tokens: 0, available_tokens: 681229, blocked: false })
    if (path === '/status') return reply(state.status)
    if (path === '/briefs/latest') return reply(state.brief)
    if (path === '/history') {
      const items = state.history.filter((entry) => !parsed.searchParams.get('report_date') || entry.report_date === parsed.searchParams.get('report_date'))
      return reply({ items, has_more: false })
    }
    if (path === '/briefs/7') return reply(state.brief)
    if (path === '/runs' && method === 'POST') return reply({ run_id: 'run-7', status: 'queued' }, 202)
    if (path === '/mail/test') return reply({ status: 'pending' })
    if (path === '/mail/test/confirm') return reply({ status: 'succeeded' })
    if (path === '/briefs/7/delivery/retry') { state.brief.delivery.status = 'pending'; return reply(state.brief.delivery, 202) }
    throw new Error(`Unexpected test API path: ${method} ${path}`)
  })
  vi.stubGlobal('fetch', fetcher)
  return { state, fetcher, reply }
}
