<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { Save, Send, UserRound, Tags, Clock3 } from '@lucide/vue'
import { topicOptions } from '../data/demo'
const props = defineProps({ preferences: Object, save: Function, mailStatus: String, mailBusy: Boolean, running: Boolean })
defineEmits(['test-email'])
const clone = (value) => JSON.parse(JSON.stringify(value))
const form = reactive(clone(props.preferences))
const errors = ref({})
const saving = ref(false)
const saved = ref(false)
const dirty = computed(() => JSON.stringify(form) !== JSON.stringify(props.preferences))
watch(() => props.preferences, (value) => { Object.assign(form, clone(value)) })
function toggleTopic(topic) {
  form.topics = form.topics.includes(topic) ? form.topics.filter((item) => item !== topic) : [...form.topics, topic]
  errors.value.topics = ''
}
async function submit() {
  if (saving.value) return
  saving.value = true
  saved.value = false
  await new Promise((resolve) => setTimeout(resolve, 250))
  const result = props.save(JSON.parse(JSON.stringify(form)))
  errors.value = result.errors
  saved.value = result.ok
  saving.value = false
  if (!result.ok) document.querySelector('[aria-invalid="true"]')?.focus()
}
function reset() { Object.assign(form, clone(props.preferences)); errors.value = {}; saved.value = false }
</script>

<template>
  <form class="settings-form" novalidate @submit.prevent="submit">
    <div class="settings-intro"><span class="eyebrow">MAKE IT YOURS</span><h2>让简报更懂你的关注</h2><p>只保留必要的信息。此处的输入仅保存在当前浏览器，不会配置真实服务。</p></div>
    <section class="form-section">
      <div class="section-heading"><UserRound :size="19" aria-hidden="true" /><h3>个人资料与收件信息</h3></div>
      <p class="section-description">称呼用于展示，邮箱用于推送；它们不是登录账号。</p>
      <div class="form-grid">
        <div class="field"><label for="name">称呼 <span>必填</span></label><input id="name" v-model="form.name" autocomplete="nickname" maxlength="40" :aria-invalid="!!errors.name" :aria-describedby="errors.name ? 'name-error' : undefined" @input="errors.name = ''; saved = false" /><p v-if="errors.name" id="name-error" class="field-error">{{ errors.name }}</p></div>
        <div class="field"><label for="role">职业或角色 <span>选填</span></label><input id="role" v-model="form.role" autocomplete="organization-title" maxlength="80" /></div>
        <div class="field full"><label for="email">收件邮箱 <span>必填</span></label><input id="email" v-model="form.email" type="email" autocomplete="email" maxlength="254" :aria-invalid="!!errors.email" :aria-describedby="errors.email ? 'email-error' : 'email-help'" @input="errors.email = ''; saved = false" /><p v-if="errors.email" id="email-error" class="field-error">{{ errors.email }}</p><p id="email-help" class="field-help">演示地址可使用 reader@example.com。请勿输入密码或 API Key。</p></div>
      </div>
      <div class="mail-test"><div><strong>邮件渠道 · 模拟配置</strong><p>不会请求 SMTP，不会发送真实邮件。请先保存收件邮箱。</p></div><button type="button" class="button secondary" :disabled="mailBusy || running || dirty" @click="$emit('test-email')"><Send :size="15" aria-hidden="true" />{{ mailBusy ? '模拟发送中…' : '模拟测试邮件' }}</button></div>
      <div v-if="mailStatus === 'success'" class="feedback success" role="status">模拟测试成功。未发送真实邮件，不代表实际邮箱已验证。</div>
      <div v-if="mailStatus === 'failed'" class="feedback error" role="status">模拟邮件服务连接失败。可以重新测试；真实 SMTP 尚未接入。</div>
    </section>
    <section class="form-section">
      <div class="section-heading"><Tags :size="19" aria-hidden="true" /><h3>订阅偏好</h3></div>
      <fieldset class="topic-fieldset"><legend>关注话题 <span>至少一项</span></legend><div class="topic-options"><button v-for="topic in topicOptions" :key="topic" type="button" :class="['topic-option', { selected: form.topics.includes(topic) }]" :aria-pressed="form.topics.includes(topic)" @click="toggleTopic(topic)">{{ topic }}</button></div><p v-if="errors.topics" class="field-error" role="alert">{{ errors.topics }}</p></fieldset>
      <div class="form-grid">
        <div class="field full"><label for="keywords">关注关键词 <span>选填</span></label><input id="keywords" v-model="form.keywords" maxlength="300" placeholder="例如：LangGraph, 开源模型" /><p class="field-help">用逗号分隔，提高相关内容的优先级。Demo 不会据此检索真实新闻。</p></div>
        <div class="field full"><label for="excluded">排除关键词 <span>选填</span></label><input id="excluded" v-model="form.excluded" maxlength="300" placeholder="例如：融资, 营销" /><p class="field-help">正式产品按标题与摘要进行字面匹配；本阶段仅保存模拟设置。</p></div>
      </div>
    </section>
    <section class="form-section">
      <div class="section-heading"><Clock3 :size="19" aria-hidden="true" /><h3>每日节奏</h3></div>
      <div class="form-grid">
        <div class="field"><label for="time">每日时间 <span>必填</span></label><input id="time" v-model="form.time" type="time" :aria-invalid="!!errors.time" /><p v-if="errors.time" class="field-error">{{ errors.time }}</p></div>
        <div class="field"><label for="timezone">时区 <span>必填</span></label><select id="timezone" v-model="form.timezone"><option value="Asia/Shanghai">中国标准时间 · UTC+8</option><option value="America/Los_Angeles">洛杉矶 · 自动区分夏令时</option><option value="UTC">协调世界时 · UTC</option></select></div>
      </div>
      <label for="enabled" class="checkbox-label"><input id="enabled" v-model="form.enabled" type="checkbox" />启用每日简报（模拟设置，不会创建定时任务）</label>
      <p class="field-help">固定每天一次 · 中文 · 约 5 条。可靠内容不足时不凑数。默认时间和时区只是演示值。</p>
    </section>
    <div v-if="errors.storage" class="feedback error" role="alert">{{ errors.storage }}</div>
    <div v-if="saved && !dirty" class="feedback success" role="status">模拟偏好已保存，刷新页面后仍可读取。</div>
    <div class="save-bar"><span>{{ dirty ? '有尚未保存的修改' : '偏好仅保存在本浏览器' }}</span><div><button type="button" class="button secondary" :disabled="!dirty || saving" @click="reset">撤销修改</button><button type="submit" class="button primary" :disabled="saving"><Save :size="16" aria-hidden="true" />{{ saving ? '保存中…' : '保存模拟偏好' }}</button></div></div>
  </form>
</template>
