<template>
  <section class="page" data-module="settle">
    <header class="page-head">
      <div>
        <h2>作业结算管理</h2>
        <p class="page-desc">按货主挂结算单；超过货主允许结算周期仍未结清的单子记为逾期，直接冻结该货主新开单。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记结算单</button>
        <button class="btn" type="button" @click="exportRows">导出作业结算清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>结算单号/客户编码</span>
        <input v-model="keyword" placeholder="按结算单号或客户编码检索" />
      </label>
      <label class="filter-item">
        <span>结算状态</span>
        <input v-model="statusFilter" placeholder="待核对/核对中…" />
      </label>
      <label class="filter-item" style="flex-direction: row; align-items: center; gap: 4px;">
        <input id="overdue-only" type="checkbox" v-model="overdueOnly" style="width: auto;" />
        <span for="overdue-only">只看逾期未结</span>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>账期/逾期</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :class="{ 'row-danger': row['授信异常'] }">
          <td>{{ row['结算单号'] ?? '—' }}</td>
          <td>{{ row['客户编码'] ?? '—' }}<span class="cell-sub">{{ row['结算对象'] }}</span></td>
          <td>{{ row['开单日期'] ?? '—' }}</td>
          <td>{{ row['结算周期'] ?? (row['客户编码'] ? '按货主授信账期' : '—') }}</td>
          <td>{{ formatMoney(row['应收金额']) }}</td>
          <td>{{ formatMoney(row['已收金额']) }}</td>
          <td>{{ row['应收未收金额'] != null ? formatMoney(row['应收未收金额']) : '—' }}</td>
          <td>{{ row.status }}</td>
          <td>
            <template v-if="row.status === '已收款'">
              <span class="badge badge-ok">已结清</span>
            </template>
            <template v-else-if="row['授信异常']">
              <span class="badge badge-danger">逾期 {{ row['逾期天数'] }} 天</span>
              <span class="cell-sub danger">截止 {{ row['账期截止日'] }}，已冻结开单</span>
            </template>
            <template v-else>
              <span class="badge badge-ok">账期内</span>
              <span class="cell-sub">截止 {{ row['账期截止日'] || '—' }}</span>
            </template>
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
          <td :colspan="columns.length + 2" class="empty-state">暂无作业结算数据，可先登记结算单</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条作业结算记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 登记结算单 -->
    <div v-if="createVisible" class="modal-mask" @click.self="createVisible = false">
      <div class="modal">
        <div class="modal-head">
          <h3>登记结算单</h3>
          <button class="modal-close" type="button" @click="createVisible = false">×</button>
        </div>
        <div v-if="createMessage" class="panel-alert danger">{{ createMessage }}</div>
        <form class="form-grid" @submit.prevent="submitCreate">
          <label class="form-field" :class="{ 'has-error': fieldErrors['结算单号'] }">
            <span>结算单号 *</span>
            <input v-model="form['结算单号']" placeholder="如 SETT-0010" />
            <span v-if="fieldErrors['结算单号']" class="field-error">{{ fieldErrors['结算单号'] }}</span>
          </label>
          <label class="form-field" :class="{ 'has-error': fieldErrors['客户编码'] }">
            <span>客户编码 *</span>
            <input v-model="form['客户编码']" placeholder="挂账货主编码" />
            <span v-if="fieldErrors['客户编码']" class="field-error">{{ fieldErrors['客户编码'] }}</span>
          </label>
          <label class="form-field" :class="{ 'has-error': fieldErrors['开单日期'] }">
            <span>开单日期 *</span>
            <input v-model="form['开单日期']" placeholder="YYYY-MM-DD" />
            <span v-if="fieldErrors['开单日期']" class="field-error">{{ fieldErrors['开单日期'] }}</span>
          </label>
          <label class="form-field" :class="{ 'has-error': fieldErrors['应收金额'] }">
            <span>应收金额（元）*</span>
            <input v-model="form['应收金额']" placeholder="不能为负数" />
            <span v-if="fieldErrors['应收金额']" class="field-error">{{ fieldErrors['应收金额'] }}</span>
          </label>
          <label class="form-field">
            <span>作业量</span>
            <input v-model="form['作业量']" placeholder="" />
          </label>
          <label class="form-field">
            <span>开票状态</span>
            <input v-model="form['开票状态']" placeholder="未开票 / 已开票" />
          </label>
          <div class="modal-foot full">
            <button class="btn ghost" type="button" @click="createVisible = false">取消</button>
            <button class="btn primary" type="submit">保存结算单</button>
          </div>
        </form>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>
type FieldErrors = Record<string, string>

const ENDPOINT = '/api/settle'
const columns = ['结算单号', '客户编码', '开单日期', '结算周期', '应收金额', '已收金额', '应收未收', '结算状态']
const actions = ['发起核对', '确认结算', '标记争议']

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')
const overdueOnly = ref(false)

const stats = computed(() => [
  { label: '未结结算单', value: rows.value.filter((r) => r.status !== '已收款').length },
  { label: '逾期未结', value: rows.value.filter((r) => r['授信异常']).length },
  { label: '应收未收合计', value: formatMoney(rows.value.reduce((s, r) => s + Number(r['应收未收金额'] ?? 0), 0)) },
])

function formatMoney(value: unknown): string {
  const n = Number(value ?? 0)
  return `¥${n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  overdueOnly.value = false
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

// ---------- 登记结算单 ----------
const createVisible = ref(false)
const createMessage = ref('')
const fieldErrors = ref<FieldErrors>({})
const emptyForm = (): Record<string, string> => ({
  结算单号: '', 客户编码: '', 开单日期: '', 应收金额: '', 作业量: '', 开票状态: '',
})
const form = reactive<Record<string, string>>(emptyForm())

function openCreate() {
  Object.assign(form, emptyForm())
  createMessage.value = ''
  fieldErrors.value = {}
  createVisible.value = true
}

async function submitCreate() {
  createMessage.value = ''
  fieldErrors.value = {}
  try {
    const response = await request(ENDPOINT, { method: 'POST', body: JSON.stringify({ values: form }) })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      fieldErrors.value = payload.details?.['字段错误'] ?? {}
      if (Object.keys(fieldErrors.value).length) {
        createMessage.value = `以下 ${Object.keys(fieldErrors.value).length} 项需要修改：${Object.values(fieldErrors.value).join('；')}`
      } else {
        createMessage.value = payload.message || '结算单登记失败'
      }
      return
    }
    createVisible.value = false
    await reload()
  } catch (error) {
    createMessage.value = error instanceof Error ? error.message : '结算单登记失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.message || '作业结算动作未生效')
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '作业结算操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value) query.set('keyword', keyword.value)
  if (statusFilter.value) query.set('status', statusFilter.value)
  if (overdueOnly.value) query.set('overdue_only', 'true')
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) throw new Error('结算单列表读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '作业结算列表读取失败'
  }
}

onMounted(reload)
</script>
