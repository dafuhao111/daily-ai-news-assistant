<script setup>
import { ArrowUpRight, Clock3, Inbox, ArrowRight } from '@lucide/vue'
import { deliveryLabel, errorMessage, formatTime } from '../api'
defineProps({ brief: Object, historical: Boolean, running: Boolean, mailBusy: Boolean, timezone: { type: String, default: 'Asia/Shanghai' } })
defineEmits(['open-article', 'run', 'retry'])
</script>

<template>
  <section aria-label="新闻简报" class="brief-view" :aria-busy="running">
    <div class="brief-masthead">
      <span class="eyebrow">{{ historical ? 'FROM YOUR ARCHIVE' : 'YOUR DAILY READING' }}</span>
      <div class="brief-title-row"><h2>{{ historical ? '那一天的 AI 简报' : '最近一期 AI 简报' }}</h2><span class="edition">{{ brief?.report_date?.replaceAll('-', '.') }}</span></div>
      <p>为你整理的 {{ brief?.item_count || 0 }} 条内容，保留来源，让阅读有据可循。</p>
      <div v-if="brief" class="brief-meta"><span><Clock3 :size="14" aria-hidden="true" />{{ formatTime(brief.generated_at, timezone) }} · {{ timezone }}</span><span>已保存 · {{ deliveryLabel(brief.delivery) }}</span></div>
    </div>
    <div v-if="running" class="inline-loading" role="status"><span class="loading-dot"></span>Agent 正在处理任务，已有内容仍可阅读。耗时取决于新闻来源与模型响应。</div>
    <div v-if="!brief || brief.run_status === 'empty'" class="empty-state">
      <Inbox :size="32" aria-hidden="true" /><h3>{{ brief ? '本期暂无符合偏好的新闻' : '还没有保存的简报' }}</h3><p>{{ brief?.empty_reason || '先保存身份与订阅偏好，再立即运行生成第一期简报。' }}</p>
      <a v-if="!brief" class="button secondary" href="#settings">设置订阅偏好<ArrowRight :size="16" aria-hidden="true" /></a>
      <button v-else-if="!historical" class="button secondary" :disabled="running" @click="$emit('run')">重新生成简报</button>
    </div>
    <template v-else>
      <div v-if="brief.delivery?.status === 'failed'" class="feedback error" role="status">邮件投递失败，简报已保存。{{ errorMessage(brief.delivery.last_error_code) }}<button class="text-button" :disabled="running || mailBusy" @click="$emit('retry', brief.id)">{{ mailBusy ? '提交中…' : '重试发送此简报' }}</button></div>
      <div v-else-if="brief.delivery?.status === 'unknown'" class="feedback neutral" role="status">邮件发送结果不确定。请先检查邮箱，避免重复发送。</div>
      <div v-else-if="brief.delivery?.status === 'skipped'" class="feedback neutral" role="status">{{ errorMessage(brief.delivery.last_error_code) }}</div>
      <ol class="article-list">
        <li v-for="(article, index) in brief.items" :key="article.article_id" class="article-row">
          <span class="article-index">{{ String(index + 1).padStart(2, '0') }}</span>
          <article><span class="article-category">{{ article.category }}</span><h3>{{ article.title }}</h3><p class="article-summary">{{ article.summary }}</p><p class="relevance"><span>与你相关</span>{{ article.relevance_reason }}</p>
            <div class="article-footer"><span>{{ article.source_name }}<span class="meta-separator">/</span><time>{{ article.published_at_utc ? formatTime(article.published_at_utc, timezone) : article.published_at_raw || '来源未提供发布时间' }}</time></span><button class="text-button" @click="$emit('open-article', article)">查看原文与来源<ArrowUpRight :size="15" aria-hidden="true" /></button></div>
          </article>
        </li>
      </ol><p class="end-note">— 摘要由 AI 基于来源材料整理，请以原文为准 —</p>
    </template>
  </section>
</template>
