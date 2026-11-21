<script setup>
import { nextTick, onMounted, onBeforeUnmount, ref } from 'vue'
import { X, ArrowUpRight } from '@lucide/vue'
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
    <div class="dialog-heading"><span class="eyebrow">DEMO ARTICLE PREVIEW</span><button class="icon-button" aria-label="关闭原文预览" @click="emit('close')"><X :size="20" aria-hidden="true" /></button></div>
    <h2 id="article-dialog-title">{{ article.title }}</h2><p class="feedback neutral">这是虚构演示文章，不是真实新闻。来源为示例名称，链接使用 example.com 占位域名。</p><p>{{ article.summary }}</p><dl class="article-facts"><dt>示例来源</dt><dd>{{ article.source }}</dd><dt>示例发布时间</dt><dd>{{ article.publishedAt }}</dd><dt>示例获取时间</dt><dd>{{ article.fetchedAt }}</dd><dt>占位链接</dt><dd>{{ article.url }}</dd></dl><a class="button secondary" :href="article.url" target="_blank" rel="noopener noreferrer">打开示例链接（非新闻原文）<ArrowUpRight :size="16" aria-hidden="true" /></a>
  </dialog>
</template>
