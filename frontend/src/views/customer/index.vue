<template>
  <section class="page" data-module="customer">
    <header class="page-head">
      <div>
        <h2>货主档案管理</h2>
        <p class="page-desc">维护货主档案与授信规则：设定授信额度与允许结算周期，开单按剩余额度与逾期情况判定。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记货主</button>
        <button class="btn" type="button" @click="exportRows">导出货主档案清单</button>
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
        <span>客户编码/名称</span>
        <input v-model="keyword" placeholder="按客户编码或名称检索" />
      </label>
      <label class="filter-item">
        <span>客户状态</span>
        <input v-model="statusFilter" placeholder="合作中/已暂停…" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>授信占用</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :class="{ 'row-danger': row['存在逾期单'] }">
          <td>{{ row['客户编码'] ?? '—' }}</td>
          <td>{{ row['客户名称'] ?? '—' }}</td>
          <td>{{ row['客户类型'] ?? '—' }}</td>
          <td>{{ row['联系人'] ?? '—' }}</td>
          <td>{{ row['联系电话'] ?? '—' }}</td>
          <td>
            <span v-if="row['存在逾期单']" class="badge badge-danger">逾期 {{ row['逾期结算单号'] }}</span>
            <span v-else-if="row['status'] === '合作中'" class="badge badge-ok">正常</span>
            <span v-else>—</span>
          </td>
          <td>{{ formatMoney(row['授信额度']) }}</td>
          <td>{{ row['允许结算周期'] != null ? `${row['允许结算周期']}天` : '—' }}</td>
          <td>
            <span class="credit-bar" :class="{ over: usageRatio(row) >= 1 }">
              <i :style="{ width: `${Math.min(usageRatio(row) * 100, 100)}%` }"></i>
            </span>
            <span class="cell-sub" :class="{ danger: usageRatio(row) >= 1 }">
              已用 {{ formatMoney(row['已占用额度']) }} / 剩 {{ formatMoney(row['剩余额度']) }}
            </span>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="openCredit(row)">授信设置</button>
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
          <td :colspan="columns.length + 2" class="empty-state">暂无货主档案数据，可先登记货主</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条货主档案记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 登记货主 -->
    <div v-if="createVisible" class="modal-mask" @click.self="createVisible = false">
      <div class="modal">
        <div class="modal-head">
          <h3>登记货主</h3>
          <button class="modal-close" type="button" @click="createVisible = false">×</button>
        </div>
        <div v-if="createMessage" class="panel-alert danger">{{ createMessage }}</div>
        <form class="form-grid" @submit.prevent="submitCreate">
          <label v-for="field in createFields" :key="field.key" class="form-field full">
            <span>{{ field.label }}<span v-if="field.required"> *</span></span>
            <input :name="`f-${field.key}`" v-model="createForm[field.key]" :placeholder="field.placeholder" />
            <span v-if="fieldErrors[field.key]" class="field-error">
              {{ fieldErrors[field.key] }}
              <button class="link" type="button" @click="focusField(field.key)">定位修改</button>
            </span>
          </label>
          <div class="modal-foot full">
            <button class="btn ghost" type="button" @click="createVisible = false">取消</button>
            <button class="btn primary" type="submit">保存货主</button>
          </div>
        </form>
      </div>
    </div>

    <!-- 授信设置 -->
    <div v-if="creditVisible" class="modal-mask" @click.self="creditVisible = false">
      <div class="modal">
        <div class="modal-head">
          <h3>授信设置 · {{ creditTarget?.['客户名称'] }}（{{ creditTarget?.['客户编码'] }}）</h3>
          <button class="modal-close" type="button" @click="creditVisible = false">×</button>
        </div>

        <div class="panel-alert warn">
          <div class="kv-line"><span>当前授信额度</span><b>{{ formatMoney(creditTarget?.['授信额度']) }}</b></div>
          <div class="kv-line"><span>已占用 / 剩余</span><b>{{ formatMoney(creditTarget?.['已占用额度']) }} / {{ formatMoney(creditTarget?.['剩余额度']) }}</b></div>
          <div class="kv-line"><span>逾期未结</span><b>{{ creditTarget?.['逾期结算单号'] || '无' }}</b></div>
        </div>
        <div v-if="creditMessage" class="panel-alert" :class="creditErrorCount ? 'danger' : 'success'">
          {{ creditMessage }}
        </div>

        <form class="form-grid" @submit.prevent="submitCredit">
          <label class="form-field full" :class="{ 'has-error': creditFieldErrors['授信额度'] }">
            <span>授信额度（元） *</span>
            <input name="credit-limit" v-model="creditForm['授信额度']" placeholder="必须为大于等于 0 的数字" />
            <span v-if="creditFieldErrors['授信额度']" class="field-error">
              {{ creditFieldErrors['授信额度'] }}
              <button class="link" type="button" @click="focusCreditField('授信额度')">定位修改</button>
            </span>
          </label>
          <label class="form-field full" :class="{ 'has-error': creditFieldErrors['允许结算周期'] }">
            <span>允许结算周期（天） *</span>
            <select name="credit-period" v-model="creditForm['允许结算周期']">
              <option value="">请选择</option>
              <option v-for="d in allowedPeriods" :key="d" :value="d">{{ d }}天</option>
            </select>
            <span v-if="creditFieldErrors['允许结算周期']" class="field-error">
              {{ creditFieldErrors['允许结算周期'] }}
              <button class="link" type="button" @click="focusCreditField('允许结算周期')">定位修改</button>
            </span>
          </label>

          <div v-if="flaggedJobs.length" class="full panel-alert danger">
            <strong>调整后以下在途作业不再合规，已在装卸任务列表标红：</strong>
            <div v-for="job in flaggedJobs" :key="job.id" class="kv-line">
              <span>{{ job['任务编号'] }}（预估 {{ formatMoney(job['预估金额']) }}）</span>
              <b>{{ job['授信异常原因'] }}</b>
            </div>
          </div>

          <div class="modal-foot full">
            <button class="btn ghost" type="button" @click="creditVisible = false">关闭</button>
            <button class="btn primary" type="submit">保存并重判在途作业</button>
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

const ENDPOINT = '/api/customer'
const columns = ['客户编码', '客户名称', '客户类型', '联系人', '联系电话', '逾期情况', '授信额度', '允许结算周期']
const actions = ['审核客户', '暂停合作', '终止合作']
const allowedPeriods = [7, 15, 30, 60, 90]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')

const stats = computed(() => [
  { label: '合作货主', value: rows.value.filter((r) => r.status === '合作中').length },
  { label: '存在逾期未结', value: rows.value.filter((r) => r['存在逾期单']).length },
  { label: '额度已用满货主', value: rows.value.filter((r) => usageRatio(r) >= 1).length },
])

function formatMoney(value: unknown): string {
  const n = Number(value ?? 0)
  return `¥${n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}
function usageRatio(row: Row): number {
  const limit = Number(row['授信额度'] ?? 0)
  const used = Number(row['已占用额度'] ?? 0)
  return limit > 0 ? used / limit : used > 0 ? 1 : 0
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

// ---------- 登记货主 ----------
const createVisible = ref(false)
const createMessage = ref('')
const fieldErrors = ref<FieldErrors>({})
const createFields = [
  { key: '客户编码', label: '客户编码', required: true, placeholder: '全局唯一，重复将被拒绝' },
  { key: '客户名称', label: '客户名称', required: true, placeholder: '' },
  { key: '客户类型', label: '客户类型', required: true, placeholder: '直客 / 物流公司' },
  { key: '联系人', label: '联系人', required: false, placeholder: '' },
  { key: '联系电话', label: '联系电话', required: false, placeholder: '' },
  { key: '授信额度', label: '授信额度（元）', required: false, placeholder: '不能为负数，不填默认 0' },
  { key: '允许结算周期', label: '允许结算周期（天，可选 7/15/30/60/90）', required: false, placeholder: '' },
]
const emptyCreateForm = (): Record<string, string> => ({
  客户编码: '', 客户名称: '', 客户类型: '', 联系人: '', 联系电话: '', 授信额度: '', 允许结算周期: '',
})
const createForm = reactive<Record<string, string>>(emptyCreateForm())

function openCreate() {
  createMessage.value = ''
  fieldErrors.value = {}
  Object.assign(createForm, emptyCreateForm())
  createVisible.value = true
}

function focusField(key: string) {
  document.querySelector<HTMLInputElement>(`.modal input[name="f-${key}"]`)?.focus()
}

async function submitCreate() {
  createMessage.value = ''
  fieldErrors.value = {}
  try {
    const response = await request(ENDPOINT, { method: 'POST', body: JSON.stringify({ values: createForm }) })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      fieldErrors.value = payload.details?.['字段错误'] ?? {}
      createMessage.value = Object.keys(fieldErrors.value).length
        ? `以下 ${Object.keys(fieldErrors.value).length} 项需要修改，可点「定位修改」`
        : payload.message || '货主登记失败'
      return
    }
    createVisible.value = false
    await reload()
  } catch (error) {
    createMessage.value = error instanceof Error ? error.message : '货主登记失败'
  }
}

// ---------- 授信设置 ----------
const creditVisible = ref(false)
const creditTarget = ref<Row | null>(null)
const creditForm = reactive<Record<string, string>>({ 授信额度: '', 允许结算周期: '' })
const creditFieldErrors = ref<FieldErrors>({})
const creditMessage = ref('')
const creditErrorCount = ref(0)
const flaggedJobs = ref<Array<Record<string, string | number>>>([])

function openCredit(row: Row) {
  creditTarget.value = row
  creditMessage.value = ''
  creditErrorCount.value = 0
  flaggedJobs.value = []
  creditFieldErrors.value = {}
  creditForm['授信额度'] = String(row['授信额度'] ?? '')
  creditForm['允许结算周期'] = String(row['允许结算周期'] ?? '')
  creditVisible.value = true
}

function focusCreditField(key: string) {
  const selector = key === '允许结算周期' ? '.modal select[name="credit-period"]' : '.modal input[name="credit-limit"]'
  document.querySelector<HTMLElement>(selector)?.focus()
}

async function submitCredit() {
  creditMessage.value = ''
  creditFieldErrors.value = {}
  flaggedJobs.value = []
  try {
    const response = await request(`${ENDPOINT}/${creditTarget.value?.id}/credit`, {
      method: 'PUT',
      body: JSON.stringify({ values: creditForm }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      creditFieldErrors.value = payload.details?.['字段错误'] ?? {}
      creditErrorCount.value = Object.keys(creditFieldErrors.value).length
      creditMessage.value = creditErrorCount.value
        ? `授信配置未保存：${Object.values(creditFieldErrors.value).join('；')}`
        : payload.message
      return
    }
    creditErrorCount.value = 0
    creditMessage.value = payload.message
    flaggedJobs.value = payload.details?.['不再合规的在途作业'] ?? []
    if (payload.entry) creditTarget.value = payload.entry
    await reload()
  } catch (error) {
    creditMessage.value = error instanceof Error ? error.message : '授信设置保存失败'
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
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || '货主档案动作未生效')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '货主档案操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value) query.set('keyword', keyword.value)
  if (statusFilter.value) query.set('status', statusFilter.value)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) throw new Error('货主列表读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '货主档案列表读取失败'
  }
}

onMounted(reload)
</script>
