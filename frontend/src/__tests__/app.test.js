import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import App from '../App.vue'

let wrapper
beforeEach(() => {
  localStorage.clear()
  location.hash = '#today'
  vi.stubGlobal('scrollTo', vi.fn())
  vi.stubGlobal('requestAnimationFrame', (callback) => { callback(); return 1 })
  vi.useFakeTimers()
})
afterEach(() => { wrapper?.unmount(); vi.unstubAllGlobals(); vi.useRealTimers(); document.body.innerHTML = '' })

async function navigate(page) {
  location.hash = `#${page}`
  window.dispatchEvent(new Event('hashchange'))
  await flushPromises()
}

it('主导航切换到设置与历史，跳过导航不会改变当前页面', async () => {
  wrapper = mount(App, { attachTo: document.body })
  expect(wrapper.findAll('.article-row')).toHaveLength(5)
  expect(wrapper.findAll('.nav-link').map((link) => link.text())).toEqual(['每日简报', '历史简报', '身份与订阅'])
  expect(wrapper.text()).not.toContain('模拟工具调用轨迹')
  await navigate('settings')
  expect(wrapper.find('#name').exists()).toBe(true)
  await wrapper.get('.skip-link').trigger('click')
  expect(location.hash).toBe('#settings')
  expect(document.activeElement.id).toBe('main-content')
  await navigate('history')
  expect(wrapper.findAll('.date-button')).toHaveLength(4)
})

it('生成简报只更新用户状态，不打开 Agent 执行详情', async () => {
  wrapper = mount(App, { attachTo: document.body })
  await wrapper.get('.page-header .primary').trigger('click')
  expect(location.hash).toBe('#today')
  expect(wrapper.text()).toContain('正在模拟整理新简报')
  await vi.runAllTimersAsync()
  await flushPromises()
  expect(location.hash).toBe('#today')
  expect(wrapper.get('[role="status"]').text()).toContain('模拟简报已更新')
  expect(wrapper.text()).not.toContain('read_file')
})

it('原文弹窗关闭后恢复按钮焦点', async () => {
  // jsdom has no native dialog implementation; browser focus trapping is checked separately.
  const showModal = vi.fn(function () { this.open = true })
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value: showModal })
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value() { this.open = false } })
  wrapper = mount(App, { attachTo: document.body })
  const open = wrapper.findAll('.article-footer button')[0]
  open.element.focus()
  await open.trigger('click')
  await flushPromises()
  expect(showModal).toHaveBeenCalled()
  expect(wrapper.get('dialog').text()).toContain('不是真实新闻')
  const close = wrapper.get('[aria-label="关闭原文预览"]')
  close.element.focus()
  await close.trigger('keydown', { key: 'Tab', shiftKey: true })
  expect(document.activeElement).toBe(wrapper.get('dialog a').element)
  await wrapper.get('dialog a').trigger('keydown', { key: 'Tab' })
  expect(document.activeElement).toBe(close.element)
  await wrapper.get('[aria-label="关闭原文预览"]').trigger('click')
  expect(wrapper.find('dialog').exists()).toBe(false)
  expect(document.activeElement).toBe(open.element)
  delete HTMLDialogElement.prototype.showModal
  delete HTMLDialogElement.prototype.close
})
