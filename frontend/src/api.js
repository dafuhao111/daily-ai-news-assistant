const messages = {
  database_not_configured: '后端尚未配置数据库，请检查本地配置后重试。',
  database_unavailable: '数据库暂时不可用，请检查服务后重试。',
  profile_not_configured: '请先保存个人资料。', preferences_not_configured: '请先保存订阅偏好。',
  mail_not_verified: '请先保存邮箱，发送测试邮件并确认收到，再启用订阅。',
  recipient_not_configured: '请先保存收件邮箱。', smtp_not_configured: '后端尚未配置 SMTP 发信服务。',
  daily_delivery_already_exists: '今天已有正在投递或已提交的简报，请查看已有内容。',
  run_already_queued: '任务正在启动，请刷新查看状态。',
  delivery_not_retryable: '此投递状态不支持重试，请刷新查看最新状态。',
  delivery_result_unknown: '发送结果不确定，请先检查邮箱，避免重复发送。',
  manual_retry_limit: '已达到手动重试上限，请检查本地后端诊断。',
  delivery_not_found: '未找到可重试的投递记录。',
  brief_not_found: '未找到这份简报，请重新选择历史记录。',
  mail_test_not_pending: '目前没有等待确认的测试邮件，请刷新状态。',
  model_timeout: '模型请求超时，可稍后重新生成。', model_request_failed: '模型服务请求失败，请检查后端配置。',
  model_error: '模型服务请求失败，请稍后重试并检查本地后端配置。',
  model_protocol_error: '模型返回格式不兼容，请检查模型接口配置。',
  iteration_limit: '任务达到工具调用轮数上限，未保存未完成的简报。',
  tool_call_limit: '任务达到单轮工具调用上限，未保存未完成的简报。',
  deadline: '任务执行超时，可稍后重新生成。',
  brief_validation_failed: '本次简报未通过格式校验，请重新生成。',
  article_not_in_task_evidence: '本次简报引用未通过校验，未保存或发送，请重新生成。',
  no_sources_configured: '尚未配置 RSS 来源，请检查本地新闻来源文件。',
  news_sources_unavailable: '新闻来源读取失败，请检查网络后重试。',
  empty_brief_without_news_evidence: '任务没有获取到可核验的新闻材料，请重新运行。',
  subscription_disabled: '订阅已暂停，未发送邮件。', smtp_timeout: '邮件请求超时，请检查投递状态。',
  smtp_permanent_rejection: '邮件服务拒绝发送，请检查邮箱配置。',
}
export const errorMessage = (code) => messages[code] || '本次操作未完成，请重试；详细原因请查看本地后端诊断。'

export class ApiError extends Error {
  constructor(code, status = 0) { super(errorMessage(code)); this.code = code; this.status = status }
}

export async function api(path, { method = 'GET', body, key, timeout = 15000 } = {}) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeout)
  try {
    const response = await fetch(`/api/v1${path}`, {
      method, signal: controller.signal, credentials: 'same-origin', cache: 'no-store',
      headers: { Accept: 'application/json', ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}), ...(key ? { 'Idempotency-Key': key } : {}) },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    })
    let data
    try { data = await response.json() } catch { throw new ApiError('invalid_response', response.status) }
    if (!response.ok) throw new ApiError(typeof data.detail === 'string' ? data.detail : 'validation_failed', response.status)
    return data
  } catch (error) {
    if (error instanceof ApiError) throw error
    throw new Error(error.name === 'AbortError' ? '请求超时。操作可能已被服务器接受，请刷新状态后重试。' : '无法连接后端，请检查网络和本地服务后重试。')
  } finally { clearTimeout(timer) }
}

export function formatTime(value, timezone = 'Asia/Shanghai') {
  if (!value) return '尚未记录'
  const utcValue = /(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}Z`
  return new Intl.DateTimeFormat('zh-CN', { timeZone: timezone, dateStyle: 'medium', timeStyle: 'short' }).format(new Date(utcValue))
}
export const runLabel = (status) => ({ queued: '等待执行', running: '正在生成简报', completed: '简报已保存', empty: '无合格新闻', failed: '生成失败', limited: '达到资源上限' }[status] || '尚未运行')
export const deliveryLabel = (delivery) => ({ pending: '等待发送', sending: '发送中', submitted: '已提交发送', failed: '投递失败', unknown: '发送状态待确认', skipped: '未发送邮件' }[delivery?.status] || '未发送邮件')
