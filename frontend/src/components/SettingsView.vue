<script setup>
import { computed, nextTick, reactive, ref } from 'vue'
import { Save, Send, UserRound, Tags, Clock3 } from '@lucide/vue'
import { topicOptions, validatePreferences } from '../data/preferences'
const props = defineProps({ preferences: Object, save: Function, saveIdentity: Function, mailStatus: String, mailBusy: Boolean, running: Boolean, smtpConfigured: Boolean, schedulerRunning: Boolean })
defineEmits(['test-email', 'confirm-email'])
const clone = (value) => JSON.parse(JSON.stringify(value))
const form = reactive(clone(props.preferences))
const errors = ref({})
const saving = ref(false)
const saved = ref(false)
const identitySaved = ref(false)
const dirty = computed(() => JSON.stringify(form) !== JSON.stringify(props.preferences))
const identityDirty = computed(() => ['name', 'role', 'email'].some((field) => form[field].trim() !== props.preferences[field]))
const emailDirty = computed(() => form.email.trim() !== props.preferences.email)
function toggleTopic(topic) {
  form.topics = form.topics.includes(topic) ? form.topics.filter((item) => item !== topic) : [...form.topics, topic]
  errors.value.topics = ''; saved.value = false
}
async function submit(identityOnly = false) {
  if (saving.value) return
  saved.value = false; identitySaved.value = false
  errors.value = validatePreferences(form, identityOnly)
  if (!Object.keys(errors.value).length) {
    saving.value = true
    try {
      const result = await (identityOnly ? props.saveIdentity : props.save)(clone(form))
      errors.value = result.errors
      if (result.ok) {
        if (identityOnly) {
          for (const field of ['name', 'role', 'email']) form[field] = props.preferences[field]
          identitySaved.value = true
        } else { Object.assign(form, clone(props.preferences)); saved.value = true }
      }
    } catch { errors.value = { server: '保存未完成，输入已保留，请重试。' } }
    finally { saving.value = false }
  }
  if (Object.keys(errors.value).length) {
    await nextTick()
    document.querySelector('.settings-form [aria-invalid="true"], .settings-form [role="alert"]')?.focus()
  }
}
function reset() { Object.assign(form, clone(props.preferences)); errors.value = {}; saved.value = false; identitySaved.value = false }
</script>

<template>
  <form class="settings-form" novalidate :aria-busy="saving" @submit.prevent="submit(false)">
    <div class="settings-intro"><span class="eyebrow">MAKE IT YOURS</span><h2>让简报更懂你的关注</h2><p>资料与偏好保存在本机数据库。修改对下一次任务生效。</p></div>
    <section class="form-section">
      <div class="section-heading"><UserRound :size="19" aria-hidden="true" /><h3>个人资料与收件信息</h3></div>
      <p class="section-description">称呼用于展示，邮箱用于推送；它们不是登录账号。</p>
      <div class="form-grid">
        <div class="field"><label for="name">称呼 <span>必填</span></label><input id="name" v-model="form.name" autocomplete="nickname" maxlength="80" :aria-invalid="!!errors.name" :aria-describedby="errors.name ? 'name-error' : undefined" @input="errors.name = ''; saved = false" /><p v-if="errors.name" id="name-error" class="field-error">{{ errors.name }}</p></div>
        <div class="field"><label for="role">职业或角色 <span>选填</span></label><input id="role" v-model="form.role" autocomplete="organization-title" maxlength="120" /></div>
        <div class="field full"><label for="email">收件邮箱 <span>启用推送前必填</span></label><input id="email" v-model="form.email" type="email" autocomplete="email" maxlength="254" :aria-invalid="!!errors.email" :aria-describedby="errors.email ? 'email-error' : 'email-help'" @input="errors.email = ''; saved = false" /><p v-if="errors.email" id="email-error" class="field-error">{{ errors.email }}</p><p id="email-help" class="field-help">请填写本人的完整邮箱。修改地址后需要重新验证。请勿输入密码或 API Key。</p></div>
      </div>
      <button type="button" class="button secondary identity-save" :disabled="saving || running || mailBusy" @click="submit(true)">保存个人资料</button>
      <p v-if="identitySaved" class="field-help" role="status">个人资料已保存。订阅偏好可在下方继续设置。</p>
      <div class="mail-test"><div><strong>邮件渠道 · {{ smtpConfigured ? 'SMTP 已配置' : '尚未配置 SMTP' }}</strong><p>只向已保存的本人邮箱发送。未保存邮箱修改时，请先保存个人资料。</p></div><button type="button" class="button secondary" :disabled="mailBusy || running || saving || identityDirty || !preferences.email || !smtpConfigured" @click="$emit('test-email')"><Send :size="15" aria-hidden="true" />{{ mailBusy ? '处理中…' : '发送 1 封测试邮件' }}</button></div>
      <div v-if="mailStatus === 'succeeded' && !emailDirty" class="feedback success" role="status">测试邮件已由你确认收到，当前邮箱已验证。</div>
      <div v-else-if="mailStatus === 'pending' && !emailDirty" class="feedback neutral" role="status">测试邮件已提交，请检查收件箱或垃圾邮件。<button type="button" class="button secondary" :disabled="mailBusy || saving || identityDirty" @click="$emit('confirm-email')">我已收到测试邮件</button></div>
      <div v-else-if="mailStatus === 'failed'" class="feedback error" role="status">测试邮件未能发送，请检查本地 SMTP 配置后重试。</div>
      <p v-else class="field-help">{{ emailDirty ? '邮箱修改尚未保存。保存新地址后需重新验证。' : '邮箱尚未验证。先发送测试邮件，实际收到后确认。' }}</p>
    </section>
    <section class="form-section">
      <div class="section-heading"><Tags :size="19" aria-hidden="true" /><h3>订阅偏好</h3></div>
      <fieldset class="topic-fieldset"><legend>关注话题 <span>至少一项</span></legend><div class="topic-options"><button v-for="topic in topicOptions" :key="topic" type="button" :class="['topic-option', { selected: form.topics.includes(topic) }]" :aria-pressed="form.topics.includes(topic)" @click="toggleTopic(topic)">{{ topic }}</button></div><p v-if="errors.topics" class="field-error" role="alert" tabindex="-1">{{ errors.topics }}</p></fieldset>
      <div class="form-grid">
        <div class="field full"><label for="keywords">关注关键词 <span>选填</span></label><input id="keywords" v-model="form.keywords" maxlength="1600" placeholder="例如：LangGraph, 开源模型" :aria-invalid="!!errors.keywords" aria-describedby="keywords-help keywords-error" @input="errors.keywords = ''" /><p id="keywords-help" class="field-help">用逗号分隔，提高相关内容的优先级；每篇新闻不必包含关键词。</p><p v-if="errors.keywords" id="keywords-error" class="field-error">{{ errors.keywords }}</p></div>
        <div class="field full"><label for="excluded">排除关键词 <span>选填</span></label><input id="excluded" v-model="form.excluded" maxlength="1600" placeholder="例如：融资, 营销" :aria-invalid="!!errors.excluded" aria-describedby="excluded-help excluded-error" @input="errors.excluded = ''" /><p id="excluded-help" class="field-help">按标题、来源摘要与简报摘要进行字面匹配，命中时排除。</p><p v-if="errors.excluded" id="excluded-error" class="field-error">{{ errors.excluded }}</p></div>
      </div>
    </section>
    <section class="form-section">
      <div class="section-heading"><Clock3 :size="19" aria-hidden="true" /><h3>每日节奏</h3></div>
      <div class="form-grid">
        <div class="field"><label for="time">每日时间 <span>必填</span></label><input id="time" v-model="form.time" type="time" :aria-invalid="!!errors.time" aria-describedby="time-error" /><p v-if="errors.time" id="time-error" class="field-error">{{ errors.time }}</p></div>
        <div class="field"><label for="timezone">时区 <span>必填</span></label><select id="timezone" v-model="form.timezone" :aria-invalid="!!errors.timezone" aria-describedby="timezone-error"><option value="Asia/Shanghai">中国标准时间 · UTC+8</option><option value="America/Los_Angeles">洛杉矶 · 自动区分夏令时</option><option value="UTC">协调世界时 · UTC</option></select><p v-if="errors.timezone" id="timezone-error" class="field-error">{{ errors.timezone }}</p></div>
      </div>
      <label for="enabled" class="checkbox-label"><input id="enabled" v-model="form.enabled" type="checkbox" />启用每日简报与邮件推送</label>
      <p class="field-help">每天一次 · 中文 · 约 5 条。启用前需验证邮箱。{{ schedulerRunning ? '调度服务正在运行。' : '后端调度未开启，保存启用状态后仍需启动调度服务。' }}电脑开机、联网且服务运行时才能执行。</p>
    </section>
    <div v-if="errors.server" class="feedback error" role="alert" tabindex="-1">{{ errors.server }}</div>
    <div v-if="saved && !dirty" class="feedback success" role="status">资料与偏好已保存，刷新页面后可从数据库读取。</div>
    <div class="save-bar"><span>{{ dirty ? '有尚未保存的修改' : '当前显示已保存的设置' }}</span><div><button type="button" class="button secondary" :disabled="!dirty || saving" @click="reset">撤销修改</button><button type="submit" class="button primary" :disabled="saving || running || mailBusy"><Save :size="16" aria-hidden="true" />{{ saving ? '保存中…' : '保存资料与偏好' }}</button></div></div>
  </form>
</template>
