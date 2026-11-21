<script setup>
import { Play, Check, CircleAlert, Terminal, ArrowRight, RotateCcw } from '@lucide/vue'
import { scenarios } from '../data/demo'
defineProps({ running: Boolean, status: String, trace: Array, scenario: String, mailBusy: Boolean })
defineEmits(['run', 'update:scenario', 'retry'])
const labels = { idle: '等待开始', running: '模拟执行中', completed: '模拟任务完成', failed: '模拟任务失败', empty: '没有合格新闻', mail_failed: '简报已保存 · 投递失败' }
const tools = ['list_dir', 'read_file', 'search_content', 'write_file', 'bash']
</script>

<template>
  <section class="agent-view">
    <div class="agent-heading"><span class="eyebrow">A LOOK INSIDE THE PROCESS</span><h2>看见一次任务如何进行</h2><p>以下为预设场景的播放，不是 LLM 决策，也不执行真实工具、文件或命令。</p></div>
    <div class="scenario-controls"><div class="field"><label for="scenario">演示场景</label><select id="scenario" :value="scenario" :disabled="running || mailBusy" @change="$emit('update:scenario', $event.target.value)"><option v-for="item in scenarios" :key="item.value" :value="item.value">{{ item.label }}</option></select></div><button class="button primary" :disabled="running || mailBusy" @click="$emit('run')"><Play :size="16" aria-hidden="true" />{{ running ? '模拟执行中…' : '开始模拟任务' }}</button></div>
    <div :class="['run-summary', { 'has-error': status === 'failed' || status === 'mail_failed' }]" role="status"><CircleAlert v-if="status === 'failed' || status === 'mail_failed'" :size="20" aria-hidden="true" /><span v-else-if="running" class="loading-dot"></span><Check v-else-if="status === 'completed'" :size="20" aria-hidden="true" /><Terminal v-else :size="20" aria-hidden="true" /><div><strong>{{ labels[status] }}</strong><p>{{ running ? '正在依次播放模拟事件，尚未完成。' : '只展示交互与状态变化，不表示真实 Agent 已实现。' }}</p></div><span class="step-count">{{ trace.length }} 个模拟事件</span></div>
    <ol v-if="trace.length" class="trace-list" aria-label="模拟工具调用轨迹" aria-live="polite" aria-relevant="additions">
      <li v-for="event in trace" :key="event.step" :class="['trace-event', event.type]"><span class="trace-marker">{{ String(event.step).padStart(2, '0') }}</span><div><div class="trace-title"><strong>{{ event.name }}</strong><span>{{ event.type === 'tool' ? '模拟工具返回' : event.type === 'model' ? '模拟决策' : '模拟状态' }}</span></div><code v-if="event.args">{{ event.args }}</code><p>{{ event.detail }}</p></div></li>
    </ol>
    <div v-else class="empty-state compact"><Terminal :size="30" aria-hidden="true" /><h3>还没有运行记录</h3><p>选择一个场景，观察开始、工具返回、继续判断和结束。</p></div>
    <div v-if="!running && trace.length" class="run-actions"><a class="button secondary" href="#today">查看每日简报<ArrowRight :size="16" aria-hidden="true" /></a><button v-if="status === 'mail_failed'" class="button primary" :disabled="mailBusy" @click="$emit('retry')"><RotateCcw :size="16" aria-hidden="true" />{{ mailBusy ? '模拟重试中…' : '只重试模拟投递' }}</button></div>
    <div class="tool-note"><h3>五个指定工具 · 后续实现范围</h3><div class="tool-tags"><code v-for="tool in tools" :key="tool">{{ tool }}</code></div><p>本阶段只有展示数据，没有注册或执行这些工具。正式 Agent 由 LLM 自主选择工具和结束时机，不强制调用全部工具；bash 将限制命令、路径和执行时间。</p></div>
  </section>
</template>
