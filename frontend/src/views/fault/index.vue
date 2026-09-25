<template>
  <section class="page" data-module="fault">
    <header class="page-head">
      <div>
        <h2>故障登记管理</h2>
        <p class="page-desc">维护设备故障，围绕故障编号、发生设备、故障现象、影响范围做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记设备故障</button>
        <button class="btn" type="button" @click="exportRows">导出故障登记清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <span
              v-if="column === '严重等级' && row[column]"
              class="grade-badge"
              :class="gradeClass(row[column])"
            >{{ row[column] }}</span>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无故障登记数据，可先登记设备故障</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条故障登记记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type StatCard = { label: string; value: number }

const ENDPOINT = '/api/fault'
const columns = ["故障编号", "发生设备", "故障现象", "影响范围", "发生时间", "报告人", "恢复时间", "严重等级", "定级依据", "处理期限", "故障状态"]
const actions = ["确认定级", "提交恢复", "挂起故障"]
const statuses = ["待定级", "已定级", "处置中", "已恢复", "已挂起"]
const grades = ["一级", "二级", "三级"]

const rows = ref<Row[]>([])
const total = ref(0)
const stats = ref<StatCard[]>([
  { label: '待定级故障', value: 0 },
  { label: '处置中故障', value: 0 },
  { label: '今日恢复数', value: 0 },
  { label: '超期未闭环', value: 0 },
])
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

function gradeClass(grade: Row[string]) {
  const key = String(grade)
  if (key === '一级') return 'grade-high'
  if (key === '二级') return 'grade-mid'
  return 'grade-low'
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '设备故障登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  const values: Record<string, string> = {}
  if (action === '确认定级') {
    const picked = window.prompt(`请选择严重等级（${grades.join(' / ')}）`, String(row['严重等级'] ?? '三级'))
    if (picked === null) {
      return
    }
    const grade = picked.trim()
    if (grade && !grades.includes(grade)) {
      errorMessage.value = `严重等级「${grade}」不在定级范围内（${grades.join('、')}）`
      return
    }
    if (grade) {
      values['严重等级'] = grade
    }
  }
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action, values }),
    })
    const result = await response.json().catch(() => null)
    if (!response.ok || (result && result.ok === false)) {
      throw new Error(result?.message || '故障登记动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '故障登记操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('设备故障列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '故障登记列表读取失败'
  }
  await loadStats()
}

async function loadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (!response.ok) {
      return
    }
    const payload = await response.json()
    if (Array.isArray(payload.cards)) {
      stats.value = payload.cards
    }
  } catch {
    // 看板刷新失败不打断列表展示
  }
}

onMounted(reload)
</script>

<style scoped>
.grade-badge {
  display: inline-block;
  min-width: 36px;
  padding: 1px 8px;
  border-radius: 10px;
  border: 1px solid transparent;
  font-size: 12px;
  line-height: 18px;
  text-align: center;
  vertical-align: middle;
}
.grade-high { background: #fef3f2; border-color: #fecdca; color: #b42318; }
.grade-mid { background: #fffaeb; border-color: #fedf89; color: #b54708; }
.grade-low { background: #eff8ff; border-color: #b2ddff; color: #175cd3; }
</style>
