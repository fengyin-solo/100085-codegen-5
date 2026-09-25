<template>
  <section class="page" data-module="loading">
    <header class="page-head">
      <div>
        <h2>装卸任务管理</h2>
        <p class="page-desc">货主赊账作业在此开单：系统按剩余授信额度判定，超额或有逾期未结结算单一律拦截。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">申请作业开单</button>
        <button class="btn" type="button" @click="exportRows">导出装卸任务清单</button>
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
        <span>任务编号</span>
        <input v-model="keyword" placeholder="按任务编号检索" />
      </label>
      <label class="filter-item">
        <span>任务状态</span>
        <input v-model="statusFilter" placeholder="待开工/作业中…" />
      </label>
      <label class="filter-item" style="flex-direction: row; align-items: center; gap: 4px;">
        <input id="abnormal-only" type="checkbox" v-model="abnormalOnly" style="width: auto;" />
        <span for="abnormal-only">只看授信异常</span>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <div v-if="rejectPanel" class="panel-alert danger">
      <strong>开单失败 · {{ rejectPanel['拦截类型'] }}</strong>
      <div style="margin-top: 6px;">{{ rejectPanel['说明'] }}</div>
      <template v-if="rejectPanel['授信判定']">
        <div v-if="rejectPanel['授信判定']['逾期单']" style="margin-top: 6px;">
          逾期单：{{ rejectPanel['授信判定']['逾期单']['结算单号'] }}，
          账期截止 {{ rejectPanel['授信判定']['逾期单']['账期截止日'] }}，
          已逾期 {{ rejectPanel['授信判定']['逾期单']['逾期天数'] }} 天，
          应收未收 {{ formatMoney(rejectPanel['授信判定']['逾期单']['应收未收金额']) }}
          <button class="link" type="button" style="margin-left: 8px;" @click="goSettle">前往结算处理</button>
        </div>
        <div v-if="rejectPanel['授信判定']['超额金额']" style="margin-top: 6px;">
          超出金额 {{ formatMoney(rejectPanel['授信判定']['超额金额']) }}：额度
          {{ formatMoney(rejectPanel['授信判定']['授信额度']) }}，已占用
          {{ formatMoney(rejectPanel['授信判定']['已占用额度']) }}，剩余额度仅
          {{ formatMoney(rejectPanel['授信判定']['剩余额度']) }}
          <button class="link" type="button" style="margin-left: 8px;" @click="goCustomer">前往调整额度</button>
        </div>
      </template>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>授信状态</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :class="{ 'row-danger': row['授信异常'] }">
          <td>{{ row['任务编号'] ?? '—' }}</td>
          <td>{{ row['客户编码'] ?? '—' }}<span class="cell-sub">{{ row['客户名称'] }}</span></td>
          <td>{{ row['作业类型'] ?? '—' }}</td>
          <td>{{ row['计划箱量'] ?? '—' }}</td>
          <td>{{ row['完成箱量'] ?? '—' }}</td>
          <td>{{ row['开始时间'] ?? '—' }}</td>
          <td>{{ formatMoney(row['预估金额']) }}</td>
          <td>{{ row['状态'] ?? row.status }}</td>
          <td>
            <span v-if="row['授信异常']" class="badge badge-danger">授信异常</span>
            <span v-else-if="row.status === '已完成'" class="badge">已完工</span>
            <span v-else class="badge badge-ok">占用中</span>
            <span v-if="row['授信异常原因']" class="cell-sub danger">{{ row['授信异常原因'] }}</span>
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
          <td :colspan="columns.length + 2" class="empty-state">暂无装卸任务数据，可先申请作业开单</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条装卸任务记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 申请开单 -->
    <div v-if="createVisible" class="modal-mask" @click.self="createVisible = false">
      <div class="modal">
        <div class="modal-head">
          <h3>申请作业开单</h3>
          <button class="modal-close" type="button" @click="createVisible = false">×</button>
        </div>
        <div v-if="createMessage" class="panel-alert danger">
          {{ createMessage }}
          <div v-if="createOverdue" style="margin-top: 6px;">
            <button class="link" type="button" @click="goSettle">前往结算处理逾期单</button>
          </div>
          <div v-if="createOver" style="margin-top: 6px;">
            <button class="link" type="button" @click="goCustomer">前往货主档案调整额度</button>
          </div>
        </div>
        <form class="form-grid" @submit.prevent="submitCreate">
          <label class="form-field" :class="{ 'has-error': fieldErrors['任务编号'] }">
            <span>任务编号 *</span>
            <input name="f-任务编号" v-model="form['任务编号']" placeholder="如 LOAD-0010" />
            <span v-if="fieldErrors['任务编号']" class="field-error">{{ fieldErrors['任务编号'] }}</span>
          </label>
          <label class="form-field" :class="{ 'has-error': fieldErrors['客户编码'] }">
            <span>客户编码 *</span>
            <input name="f-客户编码" v-model="form['客户编码']" placeholder="合作中货主编码" />
            <span v-if="fieldErrors['客户编码']" class="field-error">{{ fieldErrors['客户编码'] }}</span>
          </label>
          <label class="form-field">
            <span>作业类型 *</span>
            <input name="f-作业类型" v-model="form['作业类型']" placeholder="装船 / 卸船" />
          </label>
          <label class="form-field" :class="{ 'has-error': fieldErrors['预估金额'] }">
            <span>预估金额（元）*</span>
            <input name="f-预估金额" v-model="form['预估金额']" placeholder="本单占用授信额度" />
            <span v-if="fieldErrors['预估金额']" class="field-error">{{ fieldErrors['预估金额'] }}</span>
          </label>
          <label class="form-field">
            <span>关联航次</span>
            <input v-model="form['关联航次']" placeholder="如 VOYA-0001" />
          </label>
          <label class="form-field">
            <span>计划箱量</span>
            <input v-model="form['计划箱量']" placeholder="" />
          </label>
          <label class="form-field">
            <span>作业班组</span>
            <input v-model="form['作业班组']" placeholder="" />
          </label>
          <label class="form-field">
            <span>开始时间</span>
            <input v-model="form['开始时间']" placeholder="YYYY-MM-DD" />
          </label>
          <div class="modal-foot full">
            <button class="btn ghost" type="button" @click="createVisible = false">取消</button>
            <button class="btn primary" type="submit">提交授信校验并开单</button>
          </div>
        </form>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>
type FieldErrors = Record<string, string>

const router = useRouter()
const ENDPOINT = '/api/loading'
const columns = ['任务编号', '客户编码', '作业类型', '计划箱量', '完成箱量', '开始时间', '预估金额', '任务状态']
const actions = ['确认开工', '提交复核', '确认完成']

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')
const abnormalOnly = ref(false)
const rejectPanel = ref<Record<string, any> | null>(null)

const stats = computed(() => [
  { label: '在途作业', value: rows.value.filter((r) => r.status !== '已完成').length },
  { label: '授信异常作业', value: rows.value.filter((r) => r['授信异常']).length },
  { label: '待开工', value: rows.value.filter((r) => r.status === '待开工').length },
])

function formatMoney(value: unknown): string {
  const n = Number(value ?? 0)
  return `¥${n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}
function goSettle() { rejectPanel.value = null; void router.push('/settle') }
function goCustomer() { rejectPanel.value = null; void router.push('/customer') }

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  abnormalOnly.value = false
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

// ---------- 申请开单 ----------
const createVisible = ref(false)
const createMessage = ref('')
const createOverdue = ref(false)
const createOver = ref(false)
const fieldErrors = ref<FieldErrors>({})
const emptyForm = (): Record<string, string> => ({
  任务编号: '', 客户编码: '', 作业类型: '', 预估金额: '', 关联航次: '', 计划箱量: '', 作业班组: '', 开始时间: '',
})
const form = reactive<Record<string, string>>(emptyForm())

function openCreate() {
  Object.assign(form, emptyForm())
  createMessage.value = ''
  fieldErrors.value = {}
  createOverdue.value = false
  createOver.value = false
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
      createOverdue.value = Boolean(payload.details?.['授信判定']?.['逾期单'])
      createOver.value = Number(payload.details?.['授信判定']?.['超额金额'] ?? 0) > 0
      createMessage.value = payload.message || '开单失败'
      rejectPanel.value = payload.details ?? null
      return
    }
    createVisible.value = false
    rejectPanel.value = null
    await reload()
  } catch (error) {
    createMessage.value = error instanceof Error ? error.message : '开单失败'
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
    if (!response.ok || !payload.ok) throw new Error(payload.message || '装卸任务动作未生效')
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '装卸任务操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  rejectPanel.value = null
  const query = new URLSearchParams()
  if (keyword.value) query.set('keyword', keyword.value)
  if (statusFilter.value) query.set('status', statusFilter.value)
  if (abnormalOnly.value) query.set('abnormal', 'true')
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) throw new Error('装卸任务列表读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '装卸任务列表读取失败'
  }
}

onMounted(reload)
</script>
