import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import SettingsView from '../components/SettingsView.vue'
import HistoryView from '../components/HistoryView.vue'
import AgentView from '../components/AgentView.vue'
import BriefView from '../components/BriefView.vue'
import { defaults, initialBriefs } from '../data/demo'
import { validatePreferences } from '../composables/useDemo'

let wrapper
beforeEach(() => vi.useFakeTimers())
afterEach(() => { wrapper?.unmount(); vi.useRealTimers() })

describe('配置页面', () => {
  function settings(save = (value) => {
    const errors = validatePreferences(value)
    return { ok: !Object.keys(errors).length, errors }
  }) {
    wrapper = mount(SettingsView, { props: { preferences: structuredClone(defaults), save, mailStatus: 'idle', mailBusy: false } })
    return wrapper
  }
  it('编辑并保存完整偏好，测试邮件在未保存时不可用', async () => {
    const save = vi.fn(() => ({ ok: true, errors: {} }))
    settings(save)
    await wrapper.get('#name').setValue('我的演示称呼')
    await wrapper.get('#keywords').setValue('Agent, RSS')
    expect(wrapper.findAll('button').find((button) => button.text().includes('模拟测试邮件')).attributes('disabled')).toBeDefined()
    await wrapper.get('form').trigger('submit')
    await vi.runAllTimersAsync(); await flushPromises()
    expect(save).toHaveBeenCalledWith(expect.objectContaining({ name: '我的演示称呼', keywords: 'Agent, RSS' }))
  })
  it('必填内容错误时展示就近错误，保留输入', async () => {
    settings()
    await wrapper.get('#name').setValue('')
    await wrapper.get('#email').setValue('bad')
    await wrapper.get('form').trigger('submit')
    await vi.runAllTimersAsync(); await flushPromises()
    expect(wrapper.text()).toContain('请填写你的称呼')
    expect(wrapper.text()).toContain('请填写有效的收件邮箱')
    expect(wrapper.get('#email').element.value).toBe('bad')
  })
  it('可切换话题、撤销修改，并恢复原始表单', async () => {
    settings()
    const topic = wrapper.findAll('.topic-option').find((button) => button.text() === '多模态')
    await topic.trigger('click')
    expect(topic.attributes('aria-pressed')).toBe('true')
    await wrapper.findAll('button').find((button) => button.text() === '撤销修改').trigger('click')
    expect(topic.attributes('aria-pressed')).toBe('false')
  })
})

describe('简报、历史与运行页面', () => {
  it('原文入口返回选中文章并明确展示虚构标识', async () => {
    wrapper = mount(BriefView, { props: { brief: initialBriefs[0] } })
    expect(wrapper.text()).toContain('虚构新闻 · 演示数据')
    await wrapper.findAll('button').find((button) => button.text().includes('查看演示原文')).trigger('click')
    expect(wrapper.emitted('open-article')[0][0].url).toContain('https://example.com/demo/')
  })
  it('切换历史日期可以区分失败与无新闻', async () => {
    wrapper = mount(HistoryView, { props: { briefs: structuredClone(initialBriefs) } })
    const dates = wrapper.findAll('.date-button')
    await dates[2].trigger('click')
    expect(wrapper.text()).toContain('这一天的简报未能生成')
    await dates[3].trigger('click')
    expect(wrapper.text()).toContain('今天，让信息留一点空白')
    expect(wrapper.findAll('.article-row')).toHaveLength(0)
  })
  it('模拟运行时锁定场景，并显示运行中状态', async () => {
    wrapper = mount(AgentView, { props: { running: true, status: 'running', trace: [], scenario: 'success' } })
    expect(wrapper.get('#scenario').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('模拟执行中')
    expect(wrapper.text()).toContain('不是 LLM 决策')
  })
  it('运行页可以选择失败场景并发起模拟', async () => {
    wrapper = mount(AgentView, { props: { running: false, status: 'idle', trace: [], scenario: 'success' } })
    await wrapper.get('#scenario').setValue('failure')
    expect(wrapper.emitted('update:scenario')[0]).toEqual(['failure'])
    await wrapper.findAll('button').find((button) => button.text().includes('开始模拟任务')).trigger('click')
    expect(wrapper.emitted('run')).toHaveLength(1)
  })
})
