<script setup>
import { Newspaper, Archive, Workflow, SlidersHorizontal, ArrowUpRight, Radio } from '@lucide/vue'
defineProps({ page: String, name: String })
const links = [
  { id: 'today', label: '每日简报', icon: Newspaper },
  { id: 'history', label: '历史简报', icon: Archive },
  { id: 'agent', label: 'Agent 运行', icon: Workflow },
  { id: 'settings', label: '身份与订阅', icon: SlidersHorizontal },
]
</script>

<template>
  <aside class="sidebar">
    <a href="#today" class="brand" aria-label="每日 AI 简报首页">
      <span class="brand-symbol"><Newspaper :size="23" aria-hidden="true" /></span>
      <span>每日 AI 简报<small>DAILY SIGNAL</small></span>
    </a>
    <span class="sidebar-label">我的工作台</span>
    <nav aria-label="主导航">
      <a v-for="link in links" :key="link.id" :href="`#${link.id}`" :class="['nav-link', { active: page === link.id }]" :aria-current="page === link.id ? 'page' : undefined">
        <component :is="link.icon" :size="19" aria-hidden="true" />{{ link.label }}<span v-if="link.id === 'agent'" class="nav-demo">模拟</span>
      </a>
    </nav>
    <div class="sidebar-bottom">
      <div class="local-note"><Radio :size="17" aria-hidden="true" /><span>本机 · 单人工作区</span></div>
      <p>每天少一点噪声，<br />多一点值得关注的信号。</p>
      <a class="profile-link" href="#settings"><span class="avatar">{{ name?.slice(0, 1) || '你' }}</span><span>{{ name }}<small>演示资料</small></span><ArrowUpRight :size="16" aria-hidden="true" /></a>
    </div>
  </aside>
</template>
