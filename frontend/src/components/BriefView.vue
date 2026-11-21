<script setup>
import { ArrowUpRight, Clock3, Check, Inbox, CircleAlert, ArrowRight } from '@lucide/vue'
defineProps({ brief: Object, historical: Boolean, running: Boolean })
defineEmits(['open-article', 'run', 'retry'])
const dateLabel = (date) => date?.replaceAll('-', '.')
</script>

<template>
  <section aria-label="新闻简报" class="brief-view">
    <div class="brief-masthead">
      <span class="eyebrow">{{ historical ? 'FROM YOUR ARCHIVE' : 'YOUR DAILY READING' }}</span>
      <div class="brief-title-row"><h2>{{ historical ? '那一天的 AI 简报' : '今天，值得关注的 AI 动态' }}</h2><span class="edition">{{ dateLabel(brief?.date) }}</span></div>
      <p>为你整理的 {{ brief?.articles.length || 0 }} 条内容，保留来源，让阅读有据可循。<span class="inline-demo">虚构新闻 · 演示数据</span></p>
      <div class="brief-meta"><span><Clock3 :size="14" aria-hidden="true" />{{ brief?.generatedAt }} · 示例时间</span><span v-if="brief?.status === 'ready'"><Check :size="14" aria-hidden="true" />{{ brief.delivery === 'failed' ? '简报已保存 · 模拟投递失败' : '模拟邮件已提交' }}</span></div>
    </div>
    <div v-if="running" class="inline-loading" role="status"><span class="loading-dot"></span>正在模拟整理新简报，已有内容仍可阅读。</div>
    <div v-if="!brief || brief.status === 'empty'" class="empty-state">
      <Inbox :size="32" aria-hidden="true" /><h3>今天，让信息留一点空白</h3><p>模拟来源中没有符合偏好的新内容。不会凑数，也不会发送空简报。</p><a v-if="historical" class="button secondary" href="#today">返回每日简报<ArrowRight :size="16" aria-hidden="true" /></a><button v-else class="button secondary" @click="$emit('run')">重新生成演示简报<ArrowRight :size="16" aria-hidden="true" /></button>
    </div>
    <div v-else-if="brief.status === 'failed'" class="empty-state error-state">
      <CircleAlert :size="32" aria-hidden="true" /><h3>这一天的简报未能生成</h3><p>模拟新闻来源读取失败。这与“没有合格新闻”不同，没有发送邮件。</p><a v-if="historical" class="button secondary" href="#today">返回每日简报</a><button v-else class="button secondary" @click="$emit('run')">重新生成演示简报</button>
    </div>
    <template v-else>
      <div v-if="brief.delivery === 'failed'" class="feedback error" role="status">模拟邮件发送失败，内容已保存。<button class="text-button" :disabled="running" @click="$emit('retry')">重试投递</button></div>
      <ol class="article-list">
        <li v-for="(article, index) in brief.articles" :key="article.id" class="article-row">
          <span class="article-index">{{ String(index + 1).padStart(2, '0') }}</span>
          <article>
            <span class="article-category">{{ article.category }}</span>
            <h3>{{ article.title }}</h3>
            <p class="article-summary">{{ article.summary }}</p>
            <p class="relevance"><span>与你相关</span>{{ article.relevance }}</p>
            <div class="article-footer"><span>{{ article.source }}<span class="meta-separator">/</span><time>{{ article.publishedAt }}</time></span><button class="text-button" @click="$emit('open-article', article)">查看演示原文<ArrowUpRight :size="15" aria-hidden="true" /></button></div>
          </article>
        </li>
      </ol>
      <p class="end-note">— 本期阅读到这里 · 以上全部为虚构演示内容 —</p>
    </template>
  </section>
</template>
