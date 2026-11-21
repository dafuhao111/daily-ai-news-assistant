export const DEMO_DATE = '2026-11-20'
export const STORAGE_KEY = 'daily-ai-news-demo.preferences.v1'
export const topicOptions = ['大模型进展', 'Agent 与工具', '开源项目', 'AI 工程', '多模态', '行业动态']
export const defaults = {
  name: '小林', role: '开发者 / 技术学习者', email: 'reader@example.com',
  topics: ['大模型进展', 'Agent 与工具', '开源项目'],
  keywords: 'LangGraph, 开源模型', excluded: '融资, 营销',
  time: '08:30', timezone: 'Asia/Shanghai', enabled: true,
}

const articles = [
  { id: 'model', category: '大模型进展', title: '更小的模型，也能完成复杂任务：一项轻量推理实验', summary: '示例研究团队尝试通过任务分解与结果校验，让轻量模型处理多步骤问题。演示材料重点呈现成本、响应速度与任务完成率之间的取舍。', relevance: '与你关注的「大模型进展」相关，值得留意评测条件是否贴近实际使用。', source: '示例模型实验室', time: '07:40', path: 'lightweight-reasoning' },
  { id: 'agent', category: 'Agent 与工具', title: '让每次工具调用有迹可循：Agent 调试工作台示例', summary: '这份虚构的项目动态展示了工具参数、执行结果和失败重试的记录方式。开发者可以沿着一次任务的轨迹，定位信息不足或调用异常的环节。', relevance: '匹配关键词「LangGraph」，与你正在开发的新闻 Agent 直接相关。', source: '示例开发者周刊', time: '07:15', path: 'agent-observability' },
  { id: 'open', category: '开源项目', title: '一个面向个人开发者的 RSS 内容整理示例项目', summary: '示例项目将订阅源解析、条目去重和来源保留拆成独立模块，演示如何在有限资源下维护一条可追溯的信息处理链路。', relevance: '匹配「开源项目」，可用于理解 RSS 工程中的常见边界。', source: '示例开源社区', time: '06:50', path: 'rss-toolkit' },
  { id: 'eval', category: 'AI 工程', title: '从“能回答”到“可验证”：工具调用评测案例', summary: '示例评测区分了参数错误、工具失败和模型决策错误，强调仅看最终回答无法判断 Agent 是否正确使用工具。', relevance: '与你的 Agent 实践相关，可作为测试设计的思路参考。', source: '示例工程笔记', time: '06:20', path: 'tool-evaluation' },
  { id: 'multi', category: '多模态', title: '图文材料如何保留证据：一份多模态阅读演示', summary: '示例材料把图片描述与原始出处关联起来，展示摘要如何说明信息边界，而不是将无法核实的内容写成事实。', relevance: '作为补充阅读，关注信息可追溯性与摘要质量。', source: '示例研究观察', time: '05:45', path: 'multimodal-reading' },
]

export function makeBrief(date = DEMO_DATE, status = 'ready') {
  return {
    date, status, delivery: status === 'ready' ? 'submitted' : 'none',
    generatedAt: `${date} 08:32`,
    articles: status === 'ready' ? articles.map((article) => ({
      ...article, publishedAt: `${date} ${article.time}`,
      fetchedAt: `${date} 08:30`, url: `https://example.com/demo/${article.path}`,
    })) : [],
  }
}

export const initialBriefs = [makeBrief(), makeBrief('2026-11-19'), makeBrief('2026-11-18', 'failed'), makeBrief('2026-11-17', 'empty')]
export const scenarios = [
  { value: 'success', label: '正常完成' },
  { value: 'empty', label: '没有合格新闻' },
  { value: 'failure', label: '新闻获取失败' },
  { value: 'model_failure', label: '模型调用失败' },
  { value: 'mail_failure', label: '邮件投递失败' },
]

// Only scripted UI fixtures. No tool, command, model or network request is executed.
export function makeTrace(scenario) {
  const start = [
    { type: 'system', name: '任务开始', detail: '创建本次演示任务，加载模拟偏好概览。' },
    { type: 'model', name: '模型决策（模拟）', detail: '先读取偏好，确认本次需要关注的话题。' },
    { type: 'tool', name: 'read_file', args: '{"path":"preferences.json"}', detail: '模拟返回：3 个关注话题和关键词。' },
  ]
  if (scenario === 'model_failure') return [...start,
    { type: 'error', name: '模型响应超时（模拟）', detail: '有限重试仍未成功。任务失败，未生成简报，也未发送邮件。' },
  ]
  const fetch = { type: 'tool', name: 'fetch_rss', args: '{"source":"demo-feeds"}', detail: '模拟读取配置内 RSS；本页不会请求真实订阅源。' }
  if (scenario === 'failure') return [...start, fetch,
    { type: 'error', name: '来源读取失败（模拟）', detail: '所有示例来源均不可用。记录失败，不将其误判为没有新闻。' },
  ]
  if (scenario === 'empty') return [...start, fetch,
    { type: 'model', name: '继续判断（模拟）', detail: '候选条目可能已经报道，检查历史材料。' },
    { type: 'tool', name: 'search_content', args: '{"keyword":"候选事件","dir":"history"}', detail: '模拟返回：候选内容均已报道，无新增进展。' },
    { type: 'model', name: '结束任务（模拟）', detail: '没有合格的新内容，保存空状态，不发送空简报。' },
  ]
  return [...start, fetch,
    { type: 'model', name: '继续判断（模拟）', detail: '部分摘要信息不足，按需读取原文并核对历史。' },
    { type: 'tool', name: 'read_article', args: '{"article_id":"demo-agent"}', detail: '模拟返回：一份标明来源的示例文章内容。' },
    { type: 'tool', name: 'search_content', args: '{"keyword":"示例发布","dir":"history"}', detail: '模拟返回：未发现已收录的相同事件。' },
    { type: 'model', name: '整理简报（模拟）', detail: '证据已足够，选择 5 条演示内容并保存草稿。' },
    { type: 'tool', name: 'write_file', args: '{"path":"brief.json","content":"[演示草稿]"}', detail: '模拟保存成功；未写入宿主机文件。' },
    { type: 'model', name: '停止调用（模拟）', detail: '提交演示简报，结束模型工具调用循环。' },
    { type: scenario === 'mail_failure' ? 'error' : 'system', name: scenario === 'mail_failure' ? '邮件发送失败（模拟）' : '任务完成（模拟）', detail: scenario === 'mail_failure' ? '简报已保存，模拟 SMTP 超时。可以只重试投递。' : '简报已保存，模拟邮件服务接受请求；未发送真实邮件。' },
  ]
}
