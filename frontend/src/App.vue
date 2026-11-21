<script setup>
import { computed, nextTick, onMounted, onBeforeUnmount, ref } from 'vue'
import { ArrowRight, Play, Mail, Rss, SlidersHorizontal, Pause, CircleCheck, FlaskConical } from '@lucide/vue'
import AppSidebar from './components/AppSidebar.vue'
import BriefView from './components/BriefView.vue'
import SettingsView from './components/SettingsView.vue'
import HistoryView from './components/HistoryView.vue'
import ArticleDialog from './components/ArticleDialog.vue'
import { useDemo } from './composables/useDemo'

const demo = useDemo()
const { preferences, notice, briefs, currentBrief, running, runStatus, mailBusy, mailStatus } = demo
const pages = { today: '每日简报', history: '历史简报', settings: '身份与订阅' }
const getPage = () => Object.hasOwn(pages, location.hash.slice(1)) ? location.hash.slice(1) : 'today'
const page = ref(getPage())
const article = ref(null)
const pageHeading = ref(null)
const updatePage = async () => { page.value = getPage(); window.scrollTo({ top: 0 }); await nextTick(); pageHeading.value?.focus() }
onMounted(() => window.addEventListener('hashchange', updatePage))
onBeforeUnmount(() => window.removeEventListener('hashchange', updatePage))
const greeting = computed(() => `${preferences.value.name}，把时间留给值得读的内容。`)
function startRun() { demo.run() }
function skipToContent() { document.getElementById('main-content')?.focus() }
</script>

<template>
  <a class="skip-link" href="#main-content" @click.prevent="skipToContent">跳到主要内容</a>
  <div class="app-shell">
    <AppSidebar :page="page" :name="preferences.name" />
    <div class="workspace">
      <header class="topbar"><div><span class="workspace-name">个人工作区</span><span class="topbar-slash">/</span><span>{{ pages[page] }}</span></div><span class="local-badge"><span></span>本机前端演示</span></header>
      <main id="main-content" tabindex="-1">
        <div class="demo-banner"><FlaskConical :size="17" aria-hidden="true" /><p><strong>交互演示</strong> · 新闻和邮件均为模拟数据，未接入真实服务。</p><span class="demo-version">DEMO / 01</span></div>
        <div v-if="notice" class="notice" role="status">{{ notice }}<button class="text-button" aria-label="关闭提示" @click="notice = ''">关闭</button></div>
        <div class="page-header"><div><p class="page-kicker">{{ page === 'today' ? '星期五 / 演示日期 2026.11.20' : 'DAILY SIGNAL / 个人 AI 新闻助手' }}</p><h1 ref="pageHeading" tabindex="-1">{{ pages[page] }}</h1><p>{{ page === 'today' ? greeting : page === 'history' ? '回到某一天，重新发现值得关注的线索。' : '明确你的关注，让每天的阅读更有方向。' }}</p></div><button v-if="page === 'today'" class="button primary" :disabled="running || mailBusy" @click="startRun"><Play :size="16" aria-hidden="true" />{{ running ? '模拟生成简报中…' : '模拟生成简报' }}</button></div>

        <div v-if="page === 'today'" class="today-layout">
          <div v-if="runStatus === 'failed'" class="feedback error latest-run-error" role="status">模拟任务未能生成新简报；此前保存的内容仍保留。</div>
          <div v-else-if="runStatus === 'completed'" class="feedback success latest-run-success" role="status">模拟简报已更新，邮件状态为演示结果。</div>
          <BriefView :brief="currentBrief" :running="running" @open-article="article = $event" @run="startRun" @retry="demo.retryDelivery" />
          <aside class="reading-rail" aria-label="订阅与投递概览">
            <section class="rail-section"><div class="rail-heading"><span class="eyebrow">YOUR DAILY RHYTHM</span><CircleCheck :size="18" aria-hidden="true" /></div><h2>每天一点，持续关注</h2><div class="schedule-time">{{ preferences.time }}<span>每天 · {{ preferences.enabled ? '模拟订阅已启用' : '模拟订阅已暂停' }}</span></div><p>{{ preferences.timezone }}<br />中文 · 约 5 条 · 邮件推送</p><button class="button secondary full-width" @click="demo.setEnabled(!preferences.enabled)"><Pause v-if="preferences.enabled" :size="15" aria-hidden="true" /><Play v-else :size="15" aria-hidden="true" />{{ preferences.enabled ? '暂停模拟订阅' : '启用模拟订阅' }}</button><p class="tiny-note">仅保存开关状态，不会自动调度。</p></section>
            <section class="rail-section"><div class="rail-heading"><h2>我的关注</h2><a class="icon-button" href="#settings" aria-label="编辑关注偏好"><SlidersHorizontal :size="17" aria-hidden="true" /></a></div><div class="topic-tags"><span v-for="topic in preferences.topics" :key="topic">{{ topic }}</span></div><p class="keyword-summary">关键词<br /><strong>{{ preferences.keywords || '尚未设置' }}</strong></p><a class="text-button" href="#settings">调整订阅偏好<ArrowRight :size="15" aria-hidden="true" /></a></section>
            <section class="rail-section delivery-section"><Mail :size="19" aria-hidden="true" /><h2>简报的下一站</h2><p class="email-display">{{ preferences.email }}</p><span :class="['status-pill', { danger: currentBrief.delivery === 'failed' }]">{{ currentBrief.delivery === 'failed' ? '模拟投递失败' : currentBrief.delivery === 'submitted' ? '模拟已提交发送' : '未发送邮件' }}</span><button class="text-button" :disabled="mailBusy || running" @click="currentBrief.delivery === 'failed' ? demo.retryDelivery() : demo.testEmail()">{{ mailBusy ? '模拟处理中…' : currentBrief.delivery === 'failed' ? '重试模拟投递' : '模拟测试邮件' }}<ArrowRight :size="15" aria-hidden="true" /></button><p v-if="mailStatus === 'success'" class="field-help" role="status">模拟测试成功，未发送真实邮件。</p><p class="tiny-note">发送状态仅为演示，不代表真实送达。</p></section>
            <div class="source-note"><Rss :size="17" aria-hidden="true" /><p>来源方式：RSS<br /><span>当前新闻与来源名称均为虚构示例。</span></p></div>
          </aside>
        </div>
        <SettingsView v-else-if="page === 'settings'" :preferences="preferences" :save="demo.savePreferences" :mail-status="mailStatus" :mail-busy="mailBusy" :running="running" @test-email="demo.testEmail()" />
        <HistoryView v-else-if="page === 'history'" :briefs="briefs" @open-article="article = $event" @run="startRun" @retry="demo.retryDelivery" />
        <footer class="workspace-footer"><span>DAILY SIGNAL <span class="footer-dot">·</span> 每日 AI 简报</span><span>前端交互 Demo · 不执行真实任务</span></footer>
      </main>
    </div>
  </div>
  <ArticleDialog v-if="article" :article="article" @close="article = null" />
</template>
