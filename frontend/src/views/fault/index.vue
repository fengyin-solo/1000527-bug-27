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
              v-if="column === '严重等级'"
              class="level-badge"
              :class="levelBadgeClass(row[column])"
            >
              {{ row[column] ?? '—' }}
            </span>
            <template v-else-if="column === '故障状态'">{{ row.status ?? '—' }}</template>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <select
              v-if="classifiable(row)"
              v-model="levelDrafts[String(row.id)]"
              class="level-select"
              title="选择确认定级的严重等级"
            >
              <option v-for="level in levels" :key="level" :value="level">{{ level }}</option>
            </select>
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
type StatItem = { label: string; value: number }

const ENDPOINT = '/api/fault'
const columns = ["故障编号", "发生设备", "故障现象", "严重等级", "定级依据", "处理期限", "影响范围", "发生时间", "报告人", "恢复时间", "故障状态"]
const actions = ["确认定级", "提交恢复", "挂起故障"]
const statuses = ["待定级", "已定级", "处置中", "已恢复", "已挂起"]
const CLASSIFIABLE_STATUSES = ["待定级", "已定级"]
// 等级标识按名称映射，不按下标取，避免等级与颜色错位
const LEVEL_BADGES: Record<string, string> = { "重大": "level-danger", "较大": "level-warning", "一般": "level-calm" }

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const stats = ref<StatItem[]>([
  { label: '待定级故障', value: 0 },
  { label: '处置中故障', value: 0 },
  { label: '超期未闭环', value: 0 },
])
const levels = ref<string[]>([])
const levelDrafts = ref<Record<string, string>>({})

function classifiable(row: Row) {
  return CLASSIFIABLE_STATUSES.includes(String(row.status ?? ''))
}

function levelBadgeClass(level: Row[string]) {
  return LEVEL_BADGES[String(level ?? '')] ?? 'level-none'
}

function syncLevelDrafts() {
  for (const row of rows.value) {
    const key = String(row.id)
    if (!levelDrafts.value[key]) {
      const current = String(row['严重等级'] ?? '')
      levelDrafts.value[key] = levels.value.includes(current) ? current : (levels.value[0] ?? '')
    }
  }
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
  const body: Record<string, string> = { action }
  if (action === '确认定级') {
    body['严重等级'] = levelDrafts.value[String(row.id)] ?? ''
  }
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify(body),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || payload?.ok === false) {
      throw new Error(payload?.message ?? '故障登记动作未生效，请稍后重试')
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
    const [listResponse, statsResponse] = await Promise.all([
      request(`${ENDPOINT}?${query}`),
      request(`${ENDPOINT}/stats`),
    ])
    if (!listResponse.ok) {
      throw new Error('设备故障列表读取失败')
    }
    const payload = await listResponse.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    if (statsResponse.ok) {
      const statsPayload = await statsResponse.json()
      stats.value = statsPayload.items ?? stats.value
      levels.value = statsPayload.levels ?? levels.value
    }
    syncLevelDrafts()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '故障登记列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.level-badge {
  display: inline-block;
  min-width: 32px;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 12px;
  text-align: center;
}
.level-danger { background: #fee4e2; color: #b42318; }
.level-warning { background: #fef0c7; color: #b54708; }
.level-calm { background: #dcfae6; color: #067647; }
.level-none { background: transparent; color: var(--muted); }
.level-select {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 2px 4px;
  font-size: 12px;
  background: #fff;
}
</style>
