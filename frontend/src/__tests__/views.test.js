import { afterEach, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import SettingsView from '../components/SettingsView.vue'
import HistoryView from '../components/HistoryView.vue'
import BriefView from '../components/BriefView.vue'
import { form, brief, run, mockApi } from './apiFixtures'
import { topicOptions } from '../data/preferences'
let wrapper
afterEach(() => { wrapper?.unmount(); vi.unstubAllGlobals() })
function settings(extra = {}) {
  wrapper = mount(SettingsView, { props: { preferences: structuredClone(form), save: vi.fn(async () => ({ ok: true, errors: {} })), saveIdentity: vi.fn(async () => ({ ok: true, errors: {} })), mailStatus: 'succeeded', smtpConfigured: true, ...extra } })
  return wrapper
}
it('等待异步保存，未保存的邮箱不能发送测试邮件', async () => {
  let resolve
  const save = vi.fn(() => new Promise((done) => { resolve = done }))
  settings({ save })
  await wrapper.get('#name').setValue('新的称呼'); await wrapper.get('#email').setValue('new@example.org')
  expect(wrapper.findAll('button').find((button) => button.text().includes('发送 1 封')).attributes('disabled')).toBeDefined()
  await wrapper.get('form').trigger('submit')
  expect(wrapper.text()).toContain('保存中…')
  expect(save).toHaveBeenCalledWith(expect.objectContaining({ name: '新的称呼' }))
  resolve({ ok: false, errors: { server: '订阅偏好保存失败。请重试。' } }); await flushPromises()
  expect(wrapper.text()).toContain('订阅偏好保存失败')
  expect(wrapper.get('#name').element.value).toBe('新的称呼')
})
it('就近显示校验错误并保留输入，支持宽泛话题', async () => {
  settings()
  await wrapper.get('#name').setValue(''); await wrapper.get('#email').setValue('bad')
  await wrapper.get('form').trigger('submit'); await flushPromises()
  expect(wrapper.text()).toContain('请填写你的称呼'); expect(wrapper.text()).toContain('请填写有效的收件邮箱')
  expect(wrapper.get('#email').element.value).toBe('bad')
  for (const topic of ['AI 与学习教育', 'AI 与体育', 'AI 与日常生活']) expect(topicOptions).toContain(topic)
})
it('话题可切换并撤销，邮件提交和确认收件严格区分', async () => {
  settings({ mailStatus: 'pending' })
  const topic = wrapper.findAll('.topic-option').find((button) => button.text() === '多模态')
  await topic.trigger('click'); expect(topic.attributes('aria-pressed')).toBe('true')
  await wrapper.findAll('button').find((button) => button.text() === '撤销修改').trigger('click')
  expect(topic.attributes('aria-pressed')).toBe('false')
  expect(wrapper.text()).not.toContain('当前邮箱已验证')
  await wrapper.findAll('button').find((button) => button.text() === '我已收到测试邮件').trigger('click')
  expect(wrapper.emitted('confirm-email')).toHaveLength(1)
})
it('个人资料可先单独保存，首次配置不强制立即订阅', async () => {
  const saveIdentity = vi.fn(async () => ({ ok: true, errors: {} }))
  settings({ preferences: { ...structuredClone(form), email: '', topics: [] }, saveIdentity })
  await wrapper.findAll('button').find((button) => button.text() === '保存个人资料').trigger('click'); await flushPromises()
  expect(saveIdentity).toHaveBeenCalledOnce()
  expect(wrapper.text()).toContain('个人资料已保存')
})
it('修改称呼不误报邮箱未验证，修改邮箱提示重新验证', async () => {
  settings()
  await wrapper.get('#name').setValue('另一个称呼')
  expect(wrapper.text()).toContain('当前邮箱已验证')
  await wrapper.get('#email').setValue('other@example.org')
  expect(wrapper.text()).not.toContain('当前邮箱已验证')
  expect(wrapper.text()).toContain('保存新地址后需重新验证')
})
it('真实简报保留来源、缺失日期不编造，投递重试带简报 ID', async () => {
  wrapper = mount(BriefView, { props: { brief: { ...structuredClone(brief), delivery: { status: 'failed', last_error_code: 'smtp_timeout' } } } })
  expect(wrapper.text()).toContain('来源未提供发布时间')
  expect(wrapper.text()).toContain('邮件投递失败')
  await wrapper.findAll('button').find((button) => button.text().includes('重试发送')).trigger('click')
  expect(wrapper.emitted('retry')[0]).toEqual([7])
  await wrapper.findAll('button').find((button) => button.text().includes('查看原文')).trigger('click')
  expect(wrapper.emitted('open-article')[0][0].source_name).toBe('测试来源')
})
it('按日期读历史，生成失败与无新闻区分，支持空查询', async () => {
  const { state, fetcher } = mockApi({ history: [
    { ...run, status: 'failed', error_code: 'model_timeout', brief_id: null },
    { ...run, run_id: 'empty-run', brief_id: 7, status: 'empty' },
  ], brief: { ...brief, items: [], item_count: 0, run_status: 'empty', empty_reason: '今日没有符合偏好的新内容。' } })
  wrapper = mount(HistoryView); await flushPromises()
  expect(wrapper.text()).toContain('模型请求超时')
  await wrapper.findAll('.date-button')[1].trigger('click'); await flushPromises()
  expect(wrapper.text()).toContain('本期暂无符合偏好的新闻')
  expect(wrapper.findAll('.article-row')).toHaveLength(0)
  await wrapper.get('#history-date').setValue('2026-11-01'); await flushPromises()
  expect(wrapper.text()).toContain('这一天还没有运行记录')
  expect(fetcher.mock.calls.some(([url]) => url.includes('report_date=2026-11-01'))).toBe(true)
  state.failure = true
  await wrapper.get('#history-date').setValue('2026-11-02'); await flushPromises()
  expect(wrapper.text()).toContain('无法连接后端')
})
it('历史详情请求先后完成顺序不影响当前选中项', async () => {
  mockApi()
  wrapper = mount(HistoryView); await flushPromises()
  let finish
  vi.stubGlobal('fetch', vi.fn(() => new Promise((resolve) => { finish = resolve })))
  const old = wrapper.vm.choose({ ...run, brief_id: 7 })
  await wrapper.vm.choose({ ...run, run_id: 'failed-run', brief_id: null, status: 'failed', error_code: 'model_timeout' })
  finish({ ok: true, json: async () => brief }); await old; await flushPromises()
  expect(wrapper.text()).toContain('模型请求超时')
  expect(wrapper.findAll('.article-row')).toHaveLength(0)
})
