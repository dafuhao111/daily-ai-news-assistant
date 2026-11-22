<script setup>
import { computed, nextTick, onMounted, onBeforeUnmount, ref } from 'vue'
import { ArrowRight, Play, Mail, Rss, SlidersHorizontal, RefreshCw } from '@lucide/vue'
import AppSidebar from './components/AppSidebar.vue'
import BriefView from './components/BriefView.vue'
import SettingsView from './components/SettingsView.vue'
import HistoryView from './components/HistoryView.vue'
import ArticleDialog from './components/ArticleDialog.vue'
import { useAssistant } from './composables/useAssistant'
import { deliveryLabel, errorMessage, formatTime, runLabel } from './api'

const assistant = useAssistant()
const { preferences, notice, currentBrief, running, mailBusy, mailStatus, status, now, loading, ready, error, actionError, profileConfigured, preferencesConfigured, saving } = assistant
const pages = { today: '每日简报', history: '历史简报', settings: '身份与订阅' }
const getPage = () => Object.hasOwn(pages, location.hash.slice(1)) ? location.hash.slice(1) : 'today'
const page = ref(getPage())
const article = ref(null)
const history = ref(null)
const pageHeading = ref(null)
const updatePage = async () => { page.value = getPage(); window.scrollTo({ top: 0 }); await nextTick(); pageHeading.value?.focus() }
onMounted(() => window.addEventListener('hashchange', updatePage))
onBeforeUnmount(() => window.removeEventListener('hashchange', updatePage))
const greeting = computed(() => `${preferences.value.name || '你好'}，把时间留给值得读的内容。`)
const latest = computed(() => status.value.active_run || status.value.latest_run)
const todayLabel = computed(() => new Intl.DateTimeFormat('zh-CN', { timeZone: preferences.value.timezone, dateStyle: 'full' }).format(new Date(now.value)))
async function retryDelivery(id) { await assistant.retryDelivery(id); await history.value?.load() }
function skipToContent() { document.getElementById('main-content')?.focus() }
</script>

<template>
  <a class="skip-link" href="#main-content" @click.prevent="skipToContent">跳到主要内容</a>
  <div class="app-shell">
    <AppSidebar :page="page" :name="preferences.name" />
    <div class="workspace">
      <header class="topbar"><div><span class="workspace-name">个人工作区</span><span class="topbar-slash">/</span><span>{{ pages[page] }}</span></div><span class="local-badge"><span></span>本机数据库</span></header>
      <main id="main-content" tabindex="-1" :aria-busy="loading">
        <div v-if="notice" class="notice" role="status">{{ notice }}<button class="text-button" aria-label="关闭提示" @click="notice = ''">关闭</button></div>
        <div v-if="error" class="feedback error" role="alert">{{ error }}<button class="text-button" :disabled="loading" @click="assistant.initialize()">重新连接</button></div>
        <div v-if="actionError" class="feedback error" role="alert">{{ actionError }}</div>
        <div class="page-header"><div><p class="page-kicker">{{ page === 'today' ? todayLabel : 'DAILY SIGNAL / 个人 AI 新闻助手' }}</p><h1 ref="pageHeading" tabindex="-1">{{ pages[page] }}</h1><p>{{ page === 'today' ? greeting : page === 'history' ? '回到某一天，重新发现值得关注的线索。' : '明确你的关注，让每天的阅读更有方向。' }}</p></div><button v-if="page === 'today'" class="button primary" :disabled="loading || !!error || running || saving || mailBusy || !profileConfigured || !preferencesConfigured" :aria-busy="running" @click="assistant.run"><Play :size="16" aria-hidden="true" />{{ running ? '任务执行中…' : '立即运行' }}</button></div>
        <p v-if="loading" class="inline-loading" role="status">正在读取本机资料与简报…</p>
        <template v-else-if="ready">
          <div v-if="page === 'today'" class="today-layout">
            <section class="run-summary" :class="{ 'has-error': ['failed', 'limited'].includes(latest?.status) }" aria-label="任务状态" role="status">
              <div><strong>{{ runLabel(latest?.status) }}</strong><p v-if="latest">{{ latest.report_date }} · 开始：{{ formatTime(latest.started_at, preferences.timezone) }}<span v-if="latest.finished_at"> · 结束：{{ formatTime(latest.finished_at, preferences.timezone) }}</span></p><p v-if="latest?.error_code">{{ errorMessage(latest.error_code) }} 已保存的简报仍可阅读。</p><p v-else-if="!preferencesConfigured">先到“身份与订阅”保存资料及至少一个话题，之后即可立即运行。</p><p v-else-if="!latest">订阅已配置，可以立即生成第一期简报。</p></div><button class="icon-button" aria-label="刷新任务状态" @click="assistant.refresh().catch(failure => error = failure.message)"><RefreshCw :size="17" aria-hidden="true" /></button>
            </section>
            <BriefView :brief="currentBrief" :running="running" :mail-busy="mailBusy" :timezone="preferences.timezone" @open-article="article = $event" @run="assistant.run" @retry="retryDelivery" />
            <aside class="reading-rail" aria-label="订阅与投递概览">
              <section class="rail-section"><span class="eyebrow">YOUR DAILY RHYTHM</span><h2>每天一点，持续关注</h2><div class="schedule-time">{{ preferences.time }}<span>每天 · {{ preferences.enabled ? '订阅已启用' : '订阅已暂停' }}</span></div><p>{{ preferences.timezone }}<br />中文 · 约 5 条 · 邮件推送</p><p>{{ status.next_run_at ? `下次执行：${formatTime(status.next_run_at, preferences.timezone)}` : status.scheduler_running ? '当前没有已安排的每日任务' : '调度服务未开启' }}</p><a class="button secondary full-width" href="#settings">调整每日设置</a><p class="tiny-note">立即运行也会读取已保存偏好。订阅停用时只生成，不发送邮件。</p></section>
              <section class="rail-section"><div class="rail-heading"><h2>我的关注</h2><a class="icon-button" href="#settings" aria-label="编辑关注偏好"><SlidersHorizontal :size="17" aria-hidden="true" /></a></div><div class="topic-tags"><span v-for="topic in preferences.topics" :key="topic">{{ topic }}</span></div><p v-if="!preferences.topics.length">尚未保存关注话题</p><p class="keyword-summary">关键词<br /><strong>{{ preferences.keywords || '尚未设置' }}</strong></p><a class="text-button" href="#settings">调整订阅偏好<ArrowRight :size="15" aria-hidden="true" /></a></section>
              <section class="rail-section delivery-section"><Mail :size="19" aria-hidden="true" /><h2>简报的下一站</h2><p class="email-display">{{ preferences.email || '尚未保存收件邮箱' }}</p><span :class="['status-pill', { danger: currentBrief?.delivery?.status === 'failed' }]">{{ deliveryLabel(currentBrief?.delivery) }}</span><p>{{ mailStatus === 'succeeded' ? '收件邮箱已验证' : '收件邮箱尚未验证' }}</p><a class="text-button" href="#settings">查看邮件配置<ArrowRight :size="15" aria-hidden="true" /></a><p class="tiny-note">“已提交发送”表示 SMTP 接受请求，不代表邮件已送达。</p></section>
              <div class="source-note"><Rss :size="17" aria-hidden="true" /><p>来源方式：RSS<br /><span>来源由本地配置文件管理，简报保留原文链接。</span></p></div>
            </aside>
          </div>
          <SettingsView v-else-if="page === 'settings'" :preferences="preferences" :save="assistant.savePreferences" :save-identity="assistant.saveIdentity" :mail-status="mailStatus" :mail-busy="mailBusy" :running="running" :smtp-configured="status.smtp_configured" :scheduler-running="status.scheduler_running" @test-email="assistant.testEmail" @confirm-email="assistant.confirmEmail" />
          <HistoryView v-else-if="page === 'history'" ref="history" :timezone="preferences.timezone" :mail-busy="mailBusy" @open-article="article = $event" @retry="retryDelivery" />
        </template>
        <footer class="workspace-footer"><span>DAILY SIGNAL <span class="footer-dot">·</span> 每日 AI 简报</span><span>本机单用户 · 真实来源 · 历史保留</span></footer>
      </main>
    </div>
  </div>
  <ArticleDialog v-if="article" :article="article" @close="article = null" />
</template>
