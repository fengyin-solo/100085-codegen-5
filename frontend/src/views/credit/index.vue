<template>
  <section class="page" data-module="credit">
    <header class="page-head">
      <div>
        <h2>授信管理</h2>
        <p class="page-desc">给每个货主设定授信额度与允许结算周期；申请赊账作业时按剩余额度判定，超额或有逾期未结一律开不了单。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记授信档案</button>
        <button class="btn primary" type="button" @click="openApply">申请赊账作业</button>
        <button class="btn" type="button" @click="exportRows">导出授信清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in statCards" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form v-if="profileForm.visible" class="form-panel" @submit.prevent="submitProfile">
      <h3>{{ profileForm.id ? `调整授信档案 #${profileForm.id}（保存后会重新判定在途作业）` : '登记授信档案' }}</h3>
      <div class="form-grid">
        <label class="filter-item">
          <span>客户编码</span>
          <input v-model="profileForm.values.客户编码" :disabled="profileForm.id > 0" placeholder="如 CUST-0001" />
        </label>
        <label class="filter-item">
          <span>客户名称</span>
          <input v-model="profileForm.values.客户名称" placeholder="货主名称" />
        </label>
        <label class="filter-item">
          <span>授信额度（元）</span>
          <input v-model="profileForm.values.授信额度" type="number" step="0.01" placeholder="不能为负数" />
        </label>
        <label class="filter-item">
          <span>允许结算周期（天）</span>
          <input v-model="profileForm.values.允许结算周期" type="number" step="1" min="1" placeholder="如 30" />
        </label>
      </div>
      <div class="form-actions">
        <button class="btn primary" type="submit">{{ profileForm.id ? '保存调整并复核在途作业' : '确认登记' }}</button>
        <button class="btn ghost" type="button" @click="closeProfileForm">取消</button>
      </div>
      <p v-if="profileForm.error" class="error-text">
        {{ profileForm.error }}
        <button
          v-if="profileForm.conflict"
          class="link"
          type="button"
          @click="openEdit(profileForm.conflict)"
        >
          去修改档案 #{{ profileForm.conflict.id }}
        </button>
      </p>
    </form>

    <form v-if="applyForm.visible" class="form-panel" @submit.prevent="submitApply">
      <h3>申请赊账作业</h3>
      <div class="form-grid">
        <label class="filter-item">
          <span>客户编码</span>
          <input v-model="applyForm.values.客户编码" placeholder="如 CUST-0001" />
        </label>
        <label class="filter-item">
          <span>作业内容</span>
          <input v-model="applyForm.values.作业内容" placeholder="如 进口重箱卸船作业" />
        </label>
        <label class="filter-item">
          <span>挂账金额（元）</span>
          <input v-model="applyForm.values.挂账金额" type="number" step="0.01" min="0.01" />
        </label>
      </div>
      <div class="form-actions">
        <button class="btn primary" type="submit">提交申请</button>
        <button class="btn ghost" type="button" @click="applyForm.visible = false">取消</button>
      </div>
      <p v-if="applyForm.error" class="error-text">{{ applyForm.error }}</p>
    </form>

    <p v-if="notice" class="notice-text">{{ notice }}</p>

    <h3 class="section-title">授信档案</h3>
    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>客户编码</span>
        <input v-model="keyword" placeholder="按客户编码检索" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>
    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in profileColumns" :key="column">{{ column }}</th>
          <th>状态</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in profiles" :key="String(row.id)">
          <td v-for="column in profileColumns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>{{ row.status }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openEdit(row)">调整额度</button>
            <button
              v-for="action in profileActions(row)"
              :key="action"
              class="link"
              type="button"
              @click="runProfileAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!profiles.length">
          <td :colspan="profileColumns.length + 2" class="empty-state">暂无授信档案，可先登记授信档案</td>
        </tr>
      </tbody>
    </table>

    <h3 class="section-title">赊账作业单</h3>
    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in jobColumns" :key="column">{{ column }}</th>
          <th>复核说明</th>
          <th>状态</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in jobs" :key="String(row.id)" :class="{ 'row-flagged': row.abnormal }">
          <td v-for="column in jobColumns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>{{ row.复核说明 ?? '—' }}</td>
          <td>{{ row.status }}</td>
          <td class="row-actions">
            <button
              v-if="row.status !== '已结算'"
              class="link"
              type="button"
              @click="runJobAction('结清作业', row)"
            >
              结清作业
            </button>
          </td>
        </tr>
        <tr v-if="!jobs.length">
          <td :colspan="jobColumns.length + 3" class="empty-state">暂无赊账作业，可点击右上角申请赊账作业</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ profiles.length }} 条授信档案、{{ jobs.length }} 笔赊账作业</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type ActionPayload = { ok: boolean; message: string; entry?: Row | null }

const ENDPOINT = '/api/credit'
const profileColumns = ["客户编码", "客户名称", "授信额度", "允许结算周期", "在途挂账", "剩余额度", "逾期单数"]
const jobColumns = ["作业单号", "客户编码", "作业内容", "挂账金额", "申请日期", "约定结算日", "是否逾期"]

const profiles = ref<Row[]>([])
const jobs = ref<Row[]>([])
const summary = ref<Record<string, number>>({})
const keyword = ref('')
const errorMessage = ref('')
const notice = ref('')

const profileForm = reactive({
  visible: false,
  id: 0,
  values: { 客户编码: '', 客户名称: '', 授信额度: '', 允许结算周期: '' } as Record<string, string>,
  error: '',
  conflict: null as Row | null,
})

const applyForm = reactive({
  visible: false,
  values: { 客户编码: '', 作业内容: '', 挂账金额: '' } as Record<string, string>,
  error: '',
})

const statCards = computed(() => [
  { label: '授信货主', value: summary.value.授信货主 ?? 0 },
  { label: '在途挂账（元）', value: summary.value.在途挂账 ?? 0 },
  { label: '逾期作业单', value: summary.value.逾期作业单 ?? 0 },
  { label: '待复核作业', value: summary.value.待复核作业 ?? 0 },
])

function profileActions(row: Row) {
  return row.status === '已冻结' ? ['恢复额度'] : ['冻结额度']
}

function openCreate() {
  Object.assign(profileForm, { visible: true, id: 0, error: '', conflict: null })
  profileForm.values = { 客户编码: '', 客户名称: '', 授信额度: '', 允许结算周期: '' }
  applyForm.visible = false
  notice.value = ''
}

function openEdit(row: Row) {
  profileForm.visible = true
  profileForm.id = Number(row.id)
  profileForm.values = {
    客户编码: String(row.客户编码 ?? ''),
    客户名称: String(row.客户名称 ?? ''),
    授信额度: String(row.授信额度 ?? ''),
    允许结算周期: String(row.允许结算周期 ?? ''),
  }
  profileForm.error = ''
  profileForm.conflict = null
  applyForm.visible = false
  notice.value = ''
}

function closeProfileForm() {
  profileForm.visible = false
  profileForm.error = ''
  profileForm.conflict = null
}

function openApply() {
  applyForm.visible = true
  applyForm.error = ''
  applyForm.values = { 客户编码: '', 作业内容: '', 挂账金额: '' }
  profileForm.visible = false
  notice.value = ''
}

async function callApi(url: string, init?: RequestInit): Promise<ActionPayload> {
  const response = await request(url, init)
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(payload.detail ?? `接口返回 ${response.status}，操作未生效`)
  }
  return payload as ActionPayload
}

async function submitProfile() {
  profileForm.error = ''
  profileForm.conflict = null
  const isEdit = profileForm.id > 0
  try {
    const payload = await callApi(isEdit ? `${ENDPOINT}/${profileForm.id}` : ENDPOINT, {
      method: isEdit ? 'PUT' : 'POST',
      body: JSON.stringify({ values: { ...profileForm.values } }),
    })
    if (!payload.ok) {
      profileForm.error = payload.message
      profileForm.conflict = payload.entry ?? null
      return
    }
    notice.value = payload.message
    closeProfileForm()
    await reload()
  } catch (error) {
    profileForm.error = error instanceof Error ? error.message : '授信档案保存失败'
  }
}

async function submitApply() {
  applyForm.error = ''
  try {
    const payload = await callApi(`${ENDPOINT}/jobs`, {
      method: 'POST',
      body: JSON.stringify({ values: { ...applyForm.values } }),
    })
    if (!payload.ok) {
      applyForm.error = payload.message
      return
    }
    notice.value = payload.message
    applyForm.visible = false
    await reload()
  } catch (error) {
    applyForm.error = error instanceof Error ? error.message : '赊账作业申请失败'
  }
}

async function runProfileAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const payload = await callApi(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!payload.ok) {
      throw new Error(payload.message)
    }
    notice.value = payload.message
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '授信档案操作失败'
  }
}

async function runJobAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const payload = await callApi(`${ENDPOINT}/jobs/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!payload.ok) {
      throw new Error(payload.message)
    }
    notice.value = payload.message
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '赊账作业操作失败'
  }
}

function resetFilters() {
  keyword.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function reload() {
  errorMessage.value = ''
  const query = keyword.value ? `?keyword=${encodeURIComponent(keyword.value)}` : ''
  try {
    const [summaryRes, profileRes, jobRes] = await Promise.all([
      request(`${ENDPOINT}/summary`),
      request(`${ENDPOINT}${query}`),
      request(`${ENDPOINT}/jobs${query}`),
    ])
    if (!profileRes.ok || !jobRes.ok || !summaryRes.ok) {
      throw new Error('授信数据读取失败')
    }
    summary.value = await summaryRes.json()
    const profilePayload = await profileRes.json()
    const jobPayload = await jobRes.json()
    profiles.value = profilePayload.items ?? []
    jobs.value = jobPayload.items ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '授信数据读取失败'
  }
}

onMounted(reload)
</script>
