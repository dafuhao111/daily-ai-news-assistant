import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope } from 'vue'
import { useDemo, validatePreferences } from '../composables/useDemo'
import { defaults, makeTrace, STORAGE_KEY } from '../data/demo'

let scope
function setup(storage = localStorage) {
  scope = effectScope()
  return scope.run(() => useDemo(storage))
}
beforeEach(() => { localStorage.clear(); vi.useFakeTimers() })
afterEach(() => { scope?.stop(); vi.useRealTimers() })

describe('模拟偏好与本地持久化', () => {
  it('保存后可以重新读取，启停开关可持久化', () => {
    const demo = setup()
    expect(demo.savePreferences({ ...defaults, name: '测试读者', keywords: 'RSS' }).ok).toBe(true)
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY)).name).toBe('测试读者')
    expect(demo.setEnabled(false).ok).toBe(true)
    scope.stop()
    expect(setup().preferences.value).toMatchObject({ name: '测试读者', keywords: 'RSS', enabled: false })
  })
  it.each([
    ['name', '', 'name'], ['email', 'invalid', 'email'], ['topics', [], 'topics'],
    ['time', '25:61', 'time'], ['timezone', 'Unknown/Zone', 'timezone'],
  ])('拒绝无效的 %s', (key, value, error) => {
    expect(validatePreferences({ ...defaults, [key]: value })[error]).toBeTruthy()
  })
  it('无效输入不能覆盖已保存值', () => {
    const demo = setup()
    expect(demo.savePreferences({ ...defaults, email: 'bad' }).ok).toBe(false)
    expect(demo.preferences.value.email).toBe(defaults.email)
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull()
  })
  it('损坏或不匹配的存储恢复到默认值并提示', () => {
    localStorage.setItem(STORAGE_KEY, '{broken')
    expect(setup().notice.value).toContain('无法读取')
    scope.stop()
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...defaults, topics: ['未知话题'] }))
    expect(setup().preferences.value.topics).toEqual(defaults.topics)
  })
  it('将旧版“大模型进展”话题映射到新版宽泛选项', () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...defaults, topics: ['大模型进展', '开源项目'] }))
    expect(setup().preferences.value.topics).toEqual(['大模型与研究', '开源项目'])
  })
  it('存储不可用时不报告保存成功，也不改变已保存状态', () => {
    const demo = setup({ getItem: () => null, setItem: () => { throw new Error('quota') } })
    const result = demo.savePreferences({ ...defaults, name: '新称呼' })
    expect(result.ok).toBe(false)
    expect(result.errors.storage).toContain('保存失败')
    expect(demo.preferences.value.name).toBe(defaults.name)
  })
})

describe('预设任务场景，不调用真实服务', () => {
  it('按时间播放事件并阻止重复启动', async () => {
    const demo = setup()
    const pending = demo.run()
    expect(demo.running.value).toBe(true)
    expect(demo.trace.value).toHaveLength(0)
    await demo.run()
    await vi.advanceTimersByTimeAsync(400)
    expect(demo.trace.value).toHaveLength(1)
    await vi.runAllTimersAsync()
    await pending
    expect(demo.runStatus.value).toBe('completed')
    expect(demo.trace.value).toHaveLength(makeTrace('success').length)
    expect(demo.currentBrief.value.articles).toHaveLength(5)
  })
  it('来源或模型失败时保留已生成简报', async () => {
    const demo = setup()
    const previous = JSON.stringify(demo.currentBrief.value)
    for (const scenario of ['failure', 'model_failure']) {
      demo.scenario.value = scenario
      const pending = demo.run()
      await vi.runAllTimersAsync()
      await pending
      expect(demo.runStatus.value).toBe('failed')
      expect(JSON.stringify(demo.currentBrief.value)).toBe(previous)
      expect(demo.trace.value.at(-1).type).toBe('error')
    }
  })
  it('无合格新闻时不生成条目和投递状态', async () => {
    const demo = setup()
    demo.scenario.value = 'empty'
    const pending = demo.run()
    await vi.runAllTimersAsync()
    await pending
    expect(demo.runStatus.value).toBe('empty')
    expect(demo.currentBrief.value).toMatchObject({ status: 'empty', delivery: 'none', articles: [] })
  })
  it('投递失败后仅重试投递，复用原简报', async () => {
    const demo = setup()
    demo.scenario.value = 'mail_failure'
    let pending = demo.run()
    await vi.runAllTimersAsync()
    await pending
    expect(demo.currentBrief.value.delivery).toBe('failed')
    const articles = JSON.stringify(demo.currentBrief.value.articles)
    const previousSteps = demo.trace.value.length
    pending = demo.retryDelivery()
    await vi.runAllTimersAsync()
    await pending
    expect(demo.currentBrief.value.delivery).toBe('submitted')
    expect(JSON.stringify(demo.currentBrief.value.articles)).toBe(articles)
    expect(demo.trace.value).toHaveLength(previousSteps + 1)
  })
  it('邮件测试具有加载、失败与成功状态', async () => {
    const demo = setup()
    let pending = demo.testEmail(true)
    expect(demo.mailStatus.value).toBe('loading')
    await vi.runAllTimersAsync(); await pending
    expect(demo.mailStatus.value).toBe('failed')
    pending = demo.testEmail()
    await vi.runAllTimersAsync(); await pending
    expect(demo.mailStatus.value).toBe('success')
    demo.savePreferences({ ...defaults, email: 'other@example.com' })
    expect(demo.mailStatus.value).toBe('idle')
  })
  it('不同场景不强制使用相同轨迹', () => {
    expect(makeTrace('empty').some((event) => event.name === 'read_article')).toBe(false)
    expect(makeTrace('success').some((event) => event.name === 'read_article')).toBe(true)
    expect(makeTrace('model_failure').some((event) => event.name === 'fetch_rss')).toBe(false)
  })
  it('离开应用后取消未完成的模拟计时器', async () => {
    const demo = setup()
    const pending = demo.run()
    scope.stop()
    await pending
    expect(vi.getTimerCount()).toBe(0)
    expect(demo.trace.value).toHaveLength(0)
  })
})
