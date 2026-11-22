<script setup>
import { ref, watch, onBeforeUnmount } from 'vue'
import BriefView from './BriefView.vue'
import { api, deliveryLabel, errorMessage, formatTime, runLabel } from '../api'
defineProps({ timezone: { type: String, default: 'Asia/Shanghai' }, mailBusy: Boolean })
const emit = defineEmits(['open-article', 'retry'])
const entries = ref([])
const selected = ref(null)
const brief = ref(null)
const date = ref('')
const loading = ref(false)
const detailLoading = ref(false)
const error = ref('')
const detailError = ref('')
const hasMore = ref(false)
let listVersion = 0
let detailVersion = 0
let disposed = false
onBeforeUnmount(() => { disposed = true })
async function choose(entry) {
  const version = ++detailVersion
  selected.value = entry; brief.value = null; detailError.value = ''
  detailLoading.value = !!entry.brief_id
  if (!entry.brief_id) return
  try {
    const result = await api(`/briefs/${entry.brief_id}`)
    if (!disposed && version === detailVersion) brief.value = result
  } catch (failure) { if (!disposed && version === detailVersion) detailError.value = failure.message }
  finally { if (!disposed && version === detailVersion) detailLoading.value = false }
}
async function load(more = false) {
  if (more && loading.value) return
  const version = ++listVersion
  loading.value = true; error.value = ''
  if (!more) { ++detailVersion; entries.value = []; selected.value = null; brief.value = null; detailError.value = ''; detailLoading.value = false }
  try {
    const query = new URLSearchParams({ offset: more ? entries.value.length : 0, limit: 30 })
    if (date.value) query.set('report_date', date.value)
    const result = await api(`/history?${query}`)
    if (disposed || version !== listVersion) return
    entries.value = more ? [...entries.value, ...result.items] : result.items
    hasMore.value = result.has_more
    if (!more && entries.value.length) await choose(entries.value[0])
  } catch (failure) { if (!disposed && version === listVersion) error.value = failure.message }
  finally { if (!disposed && version === listVersion) loading.value = false }
}
watch(date, () => load(), { immediate: true })
defineExpose({ load, choose })
</script>

<template>
  <section class="history-view">
    <div class="history-intro"><span class="eyebrow">YOUR READING ARCHIVE</span><h2>把值得读的，留在这里</h2><p>按日期查看已保存的简报、生成结果和邮件投递状态。</p></div>
    <div class="history-filter"><label for="history-date">筛选日期</label><input id="history-date" v-model="date" type="date" /><button class="button secondary" :disabled="!date" @click="date = ''">全部日期</button><button class="text-button" :disabled="loading" @click="load()">刷新历史</button></div>
    <div v-if="error" class="feedback error" role="alert">{{ error }}<button class="text-button" @click="load()">重新加载</button></div>
    <p v-if="loading" class="inline-loading" role="status">正在读取历史记录…</p>
    <div v-if="!loading && !error && !entries.length" class="empty-state compact"><h3>{{ date ? '这一天还没有运行记录' : '历史将从第一期简报开始' }}</h3><p>完成一次任务后，这里会保留简报及执行结果。</p><a class="button secondary" href="#today">前往每日简报</a></div>
    <div v-if="entries.length" class="history-layout" :aria-busy="loading">
      <nav class="date-list" aria-label="历史日期">
        <button v-for="item in entries" :key="item.run_id" :class="['date-button', { selected: selected?.run_id === item.run_id }]" :aria-current="selected?.run_id === item.run_id ? 'true' : undefined" @click="choose(item)"><strong>{{ item.report_date.replaceAll('-', '.') }}</strong><span>{{ runLabel(item.status) }} · {{ formatTime(item.started_at, timezone) }}</span><span v-if="item.brief_id">{{ item.item_count }} 条 · {{ deliveryLabel(item.delivery) }}</span></button>
        <button v-if="hasMore" class="button secondary" :disabled="loading" @click="load(true)">加载更早记录</button>
      </nav>
      <div :aria-busy="detailLoading">
        <p v-if="detailLoading" class="inline-loading" role="status">正在读取简报…</p>
        <div v-else-if="detailError" class="feedback error" role="alert">{{ detailError }}<button class="text-button" @click="choose(selected)">重试读取</button></div>
        <BriefView v-else-if="brief" :brief="brief" historical :timezone="timezone" :mail-busy="mailBusy" @open-article="emit('open-article', $event)" @retry="emit('retry', $event)" />
        <div v-else-if="selected" class="empty-state compact" role="status"><h3>{{ runLabel(selected.status) }}</h3><p>{{ selected.error_code ? errorMessage(selected.error_code) : '任务尚未生成可阅读的简报，可刷新历史查看后续结果。' }}</p><a class="button secondary" href="#today">返回每日简报</a></div>
      </div>
    </div>
  </section>
</template>
