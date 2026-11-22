import { afterEach, expect, it, vi } from 'vitest'
import { api, formatTime } from '../api'
import { readdirSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })
it('API 使用 JSON 同源请求和幂等键，不回显服务端敏感错误', async () => {
  const fetcher = vi.fn(async () => ({ ok: false, status: 422, json: async () => ({ detail: [{ input: 'private key', msg: 'private' }] }) }))
  vi.stubGlobal('fetch', fetcher)
  await expect(api('/runs', { method: 'POST', body: {}, key: 'stable-key' })).rejects.toThrow('本次操作未完成')
  expect(fetcher.mock.calls[0][1]).toMatchObject({ credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': 'stable-key' } })
})
it('网络失败、非 JSON 响应和超时均转为可操作错误', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('network') }))
  await expect(api('/status')).rejects.toThrow('无法连接后端')
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => { throw new Error('html') } })))
  await expect(api('/status')).rejects.toThrow('本次操作未完成')
  vi.useFakeTimers()
  vi.stubGlobal('fetch', vi.fn((_url, { signal }) => new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new DOMException('abort', 'AbortError'))))))
  const result = expect(api('/runs', { method: 'POST', body: {}, timeout: 50 })).rejects.toThrow('操作可能已被服务器接受')
  await vi.advanceTimersByTimeAsync(50); await result
})
it('后端无时区 UTC 时间按订阅时区显示', () => {
  expect(formatTime('2026-11-22T00:30:00', 'Asia/Shanghai')).toContain('08:30')
  expect(formatTime(null)).toBe('尚未记录')
})
it('生产源码不引用旧 Demo 目录，也不引用测试夹具', () => {
  const root = resolve('src')
  function inspect(directory) {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      if (entry.name === '__tests__') continue
      const path = `${directory}/${entry.name}`
      if (entry.isDirectory()) inspect(path)
      else if (/\.(vue|js)$/.test(entry.name)) expect(readFileSync(path, 'utf8')).not.toMatch(/from\s+['"][^'"]*(?:demo|__tests__)/i)
    }
  }
  inspect(root)
})
