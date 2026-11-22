<script setup>
import { nextTick, onMounted, onBeforeUnmount, ref } from 'vue'
import { X, ArrowUpRight } from '@lucide/vue'
import { formatTime } from '../api'
defineProps({ article: Object })
const emit = defineEmits(['close'])
const dialog = ref(null)
let previousFocus
onMounted(async () => { previousFocus = document.activeElement; await nextTick(); dialog.value.showModal() })
onBeforeUnmount(() => { dialog.value?.close(); previousFocus?.focus() })
function trapFocus(event) {
  if (event.key !== 'Tab') return
  const controls = dialog.value.querySelectorAll('button, a[href]')
  const first = controls[0]
  const last = controls[controls.length - 1]
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
}
</script>

<template>
  <dialog ref="dialog" class="article-dialog" aria-labelledby="article-dialog-title" @keydown="trapFocus" @cancel.prevent="emit('close')" @click="($event.target === dialog) && emit('close')">
    <div class="dialog-heading"><span class="eyebrow">ARTICLE &amp; SOURCE</span><button class="icon-button" aria-label="关闭原文预览" @click="emit('close')"><X :size="20" aria-hidden="true" /></button></div>
    <h2 id="article-dialog-title">{{ article.title }}</h2><p class="feedback neutral">AI 概括：{{ article.summary }}</p><p><strong>来源材料摘录</strong><br />{{ article.source_excerpt || '来源未提供摘要摘录，请访问原文。' }}</p><dl class="article-facts"><dt>来源</dt><dd>{{ article.source_name }}</dd><dt>发布时间</dt><dd>{{ article.published_at_utc ? formatTime(article.published_at_utc) : article.published_at_raw || '来源未提供' }}</dd><dt>获取时间</dt><dd>{{ formatTime(article.fetched_at_utc) }} · 中国标准时间</dd><dt>原文链接</dt><dd>{{ article.url }}</dd></dl><a v-if="/^https?:\/\//i.test(article.url)" class="button secondary" :href="article.url" target="_blank" rel="noopener noreferrer">阅读新闻原文<ArrowUpRight :size="16" aria-hidden="true" /></a>
  </dialog>
</template>
