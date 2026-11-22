import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import App from '../App.vue'
import { mockApi } from './apiFixtures'

let wrapper
beforeEach(() => {
  localStorage.clear(); sessionStorage.clear(); location.hash = '#today'
  vi.stubGlobal('scrollTo', vi.fn())
  vi.useFakeTimers()
})
afterEach(() => { wrapper?.unmount(); vi.unstubAllGlobals(); vi.useRealTimers(); document.body.innerHTML = '' })
async function navigate(page) { location.hash = `#${page}`; window.dispatchEvent(new Event('hashchange')); await flushPromises() }
async function start(options) { const server = mockApi(options); wrapper = mount(App, { attachTo: document.body }); await flushPromises(); return server }

it('从真实 API 加载并切换设置、历史，跳过导航保持页面', async () => {
  const { fetcher } = await start()
  expect(wrapper.findAll('.article-row')).toHaveLength(1)
  expect(wrapper.findAll('.nav-link').map((link) => link.text())).toEqual(['每日简报', '历史简报', '身份与订阅'])
  expect(wrapper.text()).not.toMatch(/模拟|虚构|read_file/)
  await navigate('settings')
  expect(wrapper.get('#name').element.value).toBe('测试读者')
  await wrapper.get('.skip-link').trigger('click')
  expect(location.hash).toBe('#settings'); expect(document.activeElement.id).toBe('main-content')
  await navigate('history')
  expect(wrapper.findAll('.date-button')).toHaveLength(1)
  expect(fetcher.mock.calls.some(([url]) => url.startsWith('/api/v1/history'))).toBe(true)
})

it('启动 API 任务后依据后端状态轮询，刷新能恢复运行状态', async () => {
  const { state, fetcher } = await start()
  state.status.active_run = { ...state.status.latest_run, status: 'running', finished_at: null }
  await wrapper.get('.page-header .primary').trigger('click'); await flushPromises()
  const request = fetcher.mock.calls.find(([url, options]) => url === '/api/v1/runs' && options.method === 'POST')
  expect(JSON.parse(request[1].body)).toEqual({})
  expect(request[1].headers['Idempotency-Key']).toBeTruthy()
  expect(wrapper.text()).toContain('Agent 正在处理任务')
  expect(wrapper.get('.page-header .primary').attributes('disabled')).toBeDefined()
  wrapper.unmount(); wrapper = mount(App); await flushPromises()
  expect(wrapper.text()).toContain('正在生成简报')
  state.status.active_run = null
  await vi.advanceTimersByTimeAsync(2000); await flushPromises()
  expect(wrapper.get('.page-header .primary').attributes('disabled')).toBeUndefined()
  expect(wrapper.text()).not.toContain('read_file')
})

it('首次配置无示例数据，接口失败可重试且保留已填表单', async () => {
  const { state } = await start({ profile: null, preferences: null, brief: null, history: [], status: { latest_run: null, active_run: null } })
  expect(wrapper.text()).toContain('还没有保存的简报')
  expect(wrapper.get('.page-header .primary').attributes('disabled')).toBeDefined()
  await navigate('settings'); await wrapper.get('#name').setValue('未保存的称呼')
  state.failure = true
  await vi.advanceTimersByTimeAsync(10000); await flushPromises()
  expect(wrapper.text()).toContain('无法连接后端')
  state.failure = false
  await wrapper.findAll('button').find((button) => button.text() === '重新连接').trigger('click'); await flushPromises()
  expect(wrapper.get('#name').element.value).toBe('未保存的称呼')
})

it('原文弹窗区分 AI 概括与来源材料，关闭恢复焦点', async () => {
  const showModal = vi.fn(function () { this.open = true })
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value: showModal })
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value() { this.open = false } })
  await start()
  const open = wrapper.get('.article-footer button'); open.element.focus(); await open.trigger('click'); await flushPromises()
  expect(showModal).toHaveBeenCalled()
  expect(wrapper.get('dialog').text()).toContain('来源材料摘录')
  expect(wrapper.get('dialog').text()).toContain('AI 概括')
  const close = wrapper.get('[aria-label="关闭原文预览"]'); close.element.focus()
  await close.trigger('keydown', { key: 'Tab', shiftKey: true }); expect(document.activeElement).toBe(wrapper.get('dialog a').element)
  await wrapper.get('dialog a').trigger('keydown', { key: 'Tab' }); expect(document.activeElement).toBe(close.element)
  await close.trigger('click'); expect(wrapper.find('dialog').exists()).toBe(false); expect(document.activeElement).toBe(open.element)
  delete HTMLDialogElement.prototype.showModal; delete HTMLDialogElement.prototype.close
})

it('任务失败时保留上一期简报并说明原因', async () => {
  await start({ status: { latest_run: { status: 'failed', report_date: '2026-11-22', error_code: 'model_timeout' }, active_run: null } })
  expect(wrapper.text()).toContain('模型请求超时')
  expect(wrapper.findAll('.article-row')).toHaveLength(1)
})

it('表单写入真实 API 契约，刷新后从服务端恢复，加载不会发邮件', async () => {
  const { state, fetcher } = await start()
  expect(fetcher.mock.calls.every(([, options]) => options.method === 'GET')).toBe(true)
  await navigate('settings')
  await wrapper.get('#keywords').setValue('LangGraph，RSS')
  await wrapper.get('form').trigger('submit'); await flushPromises()
  expect(state.preferences.keywords).toEqual(['LangGraph', 'RSS'])
  expect(state.preferences.enabled).toBe(false)
  expect(wrapper.text()).toContain('资料与偏好已保存')
  wrapper.unmount(); wrapper = mount(App); await flushPromises()
  expect(wrapper.get('#keywords').element.value).toBe('LangGraph, RSS')
  expect(fetcher.mock.calls.some(([url]) => url.includes('/mail/test'))).toBe(false)
})

it('提交响应丢失后重试复用幂等键，成功后清除待确认键', async () => {
  const { fetcher } = await start()
  let failed = false
  vi.stubGlobal('fetch', vi.fn(async (url, options) => {
    if (url === '/api/v1/runs' && !failed) { failed = true; throw new TypeError('lost response') }
    return fetcher(url, options)
  }))
  await wrapper.get('.page-header .primary').trigger('click'); await flushPromises()
  const key = sessionStorage.getItem('daily-ai-pending-run')
  expect(key).toBeTruthy()
  expect(wrapper.text()).toContain('无法连接后端')
  await wrapper.get('.page-header .primary').trigger('click'); await flushPromises()
  const accepted = fetcher.mock.calls.find(([url]) => url === '/api/v1/runs')
  expect(accepted[1].headers['Idempotency-Key']).toBe(key)
  expect(sessionStorage.getItem('daily-ai-pending-run')).toBeNull()
})

it('首次加载失败保留错误入口，重新连接后恢复页面', async () => {
  const { state } = await start({ failure: true })
  expect(wrapper.text()).toContain('无法连接后端')
  expect(wrapper.find('.today-layout').exists()).toBe(false)
  state.failure = false
  await wrapper.findAll('button').find((button) => button.text() === '重新连接').trigger('click'); await flushPromises()
  expect(wrapper.findAll('.article-row')).toHaveLength(1)
  wrapper.unmount()
  expect(vi.getTimerCount()).toBe(0)
})
it('页面跨中国时区午夜后更新日期，报告日期继续来自后端', async () => {
  vi.setSystemTime(new Date('2026-11-22T15:59:59Z'))
  await start()
  expect(wrapper.get('.page-kicker').text()).toContain('2026年11月22日')
  await vi.advanceTimersByTimeAsync(10000); await flushPromises()
  expect(wrapper.get('.page-kicker').text()).toContain('2026年11月23日')
  expect(wrapper.get('.edition').text()).toBe('2026.11.22')
})
it('后端复用当天任务时不伪装为新任务或再次投递', async () => {
  const { fetcher, reply } = await start()
  vi.stubGlobal('fetch', vi.fn((url, options) => url === '/api/v1/runs'
    ? Promise.resolve(reply({ run_id: 'run-7', status: 'completed' })) : fetcher(url, options)))
  await wrapper.get('.page-header .primary').trigger('click'); await flushPromises()
  expect(wrapper.text()).toContain('未重复生成或发送')
  expect(fetcher.mock.calls.some(([url]) => url.includes('/delivery/retry'))).toBe(false)
})
