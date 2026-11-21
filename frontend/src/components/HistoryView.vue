<script setup>
import { ref, computed } from 'vue'
import BriefView from './BriefView.vue'
const props = defineProps({ briefs: Array })
defineEmits(['open-article', 'run', 'retry'])
const selected = ref(props.briefs[0]?.date)
const brief = computed(() => props.briefs.find((item) => item.date === selected.value))
const statusLabel = (item) => item.status === 'failed' ? '生成失败' : item.status === 'empty' ? '无合格新闻' : `${item.articles.length} 条 · ${item.delivery === 'failed' ? '投递失败' : '已提交（模拟）'}`
</script>

<template>
  <section class="history-view"><div class="history-intro"><span class="eyebrow">YOUR READING ARCHIVE</span><h2>把值得读的，留在这里</h2><p>切换日期，查看不同状态的模拟简报。历史内容为虚构，刷新后恢复示例。</p></div>
    <div class="history-layout"><nav class="date-list" aria-label="历史日期"><button v-for="item in briefs" :key="item.date" :class="['date-button', { selected: selected === item.date }]" :aria-current="selected === item.date ? 'date' : undefined" @click="selected = item.date"><strong>{{ item.date.replaceAll('-', '.') }}</strong><span>{{ statusLabel(item) }}</span></button></nav><BriefView :brief="brief" historical @open-article="$emit('open-article', $event)" @run="$emit('run')" @retry="$emit('retry')" /></div>
  </section>
</template>
