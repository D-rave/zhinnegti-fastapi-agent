<template>
  <div class="dashboard-page">
    <el-page-header @back="router.back()" title="用量监控大盘" />

    <!-- 核心指标卡片 -->
    <el-row :gutter="20" class="metric-cards">
      <el-col :xs="12" :sm="8" :md="6">
        <el-card shadow="hover">
          <div class="metric-icon">💰</div>
          <div class="metric-value">¥{{ usageStats.daily_spent?.toFixed(4) || '0.0000' }}</div>
          <div class="metric-label">今日模型费用</div>
          <div class="metric-sub">预算: ¥{{ usageStats.daily_budget || '∞' }}</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="8" :md="6">
        <el-card shadow="hover">
          <div class="metric-icon">🤖</div>
          <div class="metric-value">{{ usageStats.total_calls || 0 }}</div>
          <div class="metric-label">今日 LLM 调用</div>
          <div class="metric-sub">剩余: ¥{{ usageStats.daily_remaining?.toFixed(4) || '∞' }}</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="8" :md="6">
        <el-card shadow="hover">
          <div class="metric-icon">💬</div>
          <div class="metric-value">{{ stats.total_sessions || 0 }}</div>
          <div class="metric-label">总会话数</div>
          <div class="metric-sub">消息: {{ stats.total_messages || 0 }}</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="8" :md="6">
        <el-card shadow="hover">
          <div class="metric-icon">📚</div>
          <div class="metric-value">{{ stats.knowledge_files || 0 }}</div>
          <div class="metric-label">知识库文件</div>
          <div class="metric-sub">全局共享</div>
        </el-card>
      </el-col>
    </el-row>

    <el-tabs v-model="activeTab" class="dashboard-tabs">
      <!-- 用量明细 -->
      <el-tab-pane label="用量明细" name="usage">
        <el-card>
          <template #header>
            <div class="card-header">
              <span>Token 用量详情</span>
              <el-button type="primary" size="small" @click="loadUsage">刷新</el-button>
            </div>
          </template>
          <el-descriptions :column="3" border>
            <el-descriptions-item label="今日费用">¥{{ usageStats.daily_spent?.toFixed(6) || '0' }}</el-descriptions-item>
            <el-descriptions-item label="日预算">¥{{ usageStats.daily_budget || '∞' }}</el-descriptions-item>
            <el-descriptions-item label="剩余预算">¥{{ usageStats.daily_remaining?.toFixed(6) || '∞' }}</el-descriptions-item>
            <el-descriptions-item label="LLM 调用次数">{{ usageStats.total_calls || 0 }}</el-descriptions-item>
            <el-descriptions-item label="Buffer 费用">¥{{ usageStats.buffer_cost?.toFixed(6) || '0' }}</el-descriptions-item>
            <el-descriptions-item label="Buffer Tokens">{{ usageStats.buffer_tokens || 0 }}</el-descriptions-item>
          </el-descriptions>

          <el-divider />
          <h4>模型单价参考</h4>
          <el-table :data="pricingData" border size="small">
            <el-table-column prop="model" label="模型" />
            <el-table-column prop="input" label="输入 (元/1K tokens)" />
            <el-table-column prop="output" label="输出 (元/1K tokens)" />
          </el-table>
        </el-card>
      </el-tab-pane>

      <!-- 知识库管理 -->
      <el-tab-pane label="知识库" name="knowledge">
        <div class="knowledge-toolbar">
          <el-button type="warning" @click="rebuildVectorStore" :loading="rebuilding">
            重建向量库
          </el-button>
          <el-button type="primary" @click="uploadDialogVisible = true">
            上传文件
          </el-button>
        </div>

        <el-table :data="knowledgeList" v-loading="knowledgeLoading" border>
          <el-table-column prop="filename" label="文件名" min-width="200" />
          <el-table-column prop="size" label="大小" width="120">
            <template #default="{ row }">
              {{ formatSize(row.size) }}
            </template>
          </el-table-column>
          <el-table-column prop="chunks" label="片段数" width="100">
            <template #default="{ row }">
              {{ row.chunks || '-' }}
            </template>
          </el-table-column>
          <el-table-column prop="uploaded_at" label="上传时间" width="180">
            <template #default="{ row }">
              {{ formatDate(row.uploaded_at) }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="120" fixed="right">
            <template #default="{ row }">
              <el-button type="danger" size="small" @click="deleteKnowledge(row.filename)">
                删除
              </el-button>
            </template>
          </el-table-column>
        </el-table>

        <el-empty v-if="!knowledgeLoading && knowledgeList.length === 0" description="暂无知识库文件" />
      </el-tab-pane>

      <!-- 系统配置 -->
      <el-tab-pane label="预算设置" name="settings">
        <el-card>
          <el-form :model="settings" label-width="120px">
            <el-form-item label="日预算 (CNY)">
              <el-input-number v-model="settings.dailyBudget" :min="0" :precision="2" />
              <span class="form-tip">0 表示无限制</span>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="saveSettings">保存预算</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <!-- 上传对话框 -->
    <el-dialog v-model="uploadDialogVisible" title="上传知识库文件" width="500px">
      <el-upload
        ref="uploadRef"
        action="#"
        :auto-upload="false"
        :on-change="handleFileChange"
        :limit="5"
        multiple
        accept=".pdf,.txt,.docx,.md"
      >
        <el-button type="primary">选择文件</el-button>
        <template #tip>
          <div class="el-upload__tip">
            支持 PDF、TXT、DOCX、MD 格式
          </div>
        </template>
      </el-upload>
      <template #footer>
        <el-button @click="uploadDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitUpload" :loading="uploading">
          上传
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { ElMessage, ElMessageBox } from 'element-plus'

const router = useRouter()
const userStore = useUserStore()
const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8011/api'

const activeTab = ref('usage')
const knowledgeLoading = ref(false)
const uploading = ref(false)
const rebuilding = ref(false)
const uploadDialogVisible = ref(false)
const uploadRef = ref(null)
const selectedFiles = ref([])

const knowledgeList = ref([])
const stats = ref({ total_sessions: 0, total_messages: 0, knowledge_files: 0 })
const usageStats = ref({})

const settings = ref({
  dailyBudget: 0
})

const pricingData = ref([
  { model: 'qwen-max', input: '0.0024', output: '0.0096' },
  { model: 'text-embedding-v4', input: '0.0005', output: '0.0' }
])

const apiFetch = async (url, options = {}) => {
  const token = userStore.token
  const headers = {
    ...options.headers,
    'Authorization': token ? `Bearer ${token}` : ''
  }
  if (options.body && !(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json'
  }
  const res = await fetch(`${BASE_URL}${url}`, { ...options, headers })
  if (res.status === 401) {
    userStore.logout()
    window.location.href = '/login'
    throw new Error('登录已过期')
  }
  const data = await res.json()
  if (!data.success && data.message) {
    throw new Error(data.message)
  }
  return data
}

const loadKnowledgeList = async () => {
  knowledgeLoading.value = true
  try {
    const res = await apiFetch('/admin/knowledge/list')
    if (res.success) {
      knowledgeList.value = res.data || []
    }
  } catch (e) {
    ElMessage.error('加载知识库失败: ' + e.message)
  } finally {
    knowledgeLoading.value = false
  }
}

const formatSize = (bytes) => {
  if (!bytes) return '-'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

const formatDate = (timestamp) => {
  if (!timestamp) return '-'
  return new Date(timestamp * 1000).toLocaleString()
}

const handleFileChange = (file, fileList) => {
  selectedFiles.value = fileList
}

const submitUpload = async () => {
  if (selectedFiles.value.length === 0) {
    ElMessage.warning('请选择文件')
    return
  }
  uploading.value = true
  try {
    const formData = new FormData()
    selectedFiles.value.forEach(file => {
      formData.append('files', file.raw)
    })
    const res = await apiFetch('/admin/knowledge/batch-upload', {
      method: 'POST',
      body: formData
    })
    if (res.success) {
      ElMessage.success(res.message)
      uploadDialogVisible.value = false
      selectedFiles.value = []
      uploadRef.value?.clearFiles()
      loadKnowledgeList()
      loadStats()
    } else {
      ElMessage.error(res.message || '上传失败')
    }
  } catch (e) {
    ElMessage.error('上传失败: ' + e.message)
  } finally {
    uploading.value = false
  }
}

const deleteKnowledge = async (filename) => {
  try {
    await ElMessageBox.confirm(`确定删除 ${filename} 吗？`, '确认删除', { type: 'warning' })
    const res = await apiFetch(`/admin/knowledge/${encodeURIComponent(filename)}`, {
      method: 'DELETE'
    })
    if (res.success) {
      ElMessage.success('删除成功')
      loadKnowledgeList()
      loadStats()
    }
  } catch (e) {
    if (e !== 'cancel') {
      ElMessage.error('删除失败: ' + e.message)
    }
  }
}

const rebuildVectorStore = async () => {
  try {
    await ElMessageBox.confirm('重建向量库会清空现有数据并重新索引，确定继续吗？', '确认重建', { type: 'warning' })
    rebuilding.value = true
    const res = await apiFetch('/admin/knowledge/rebuild', { method: 'POST' })
    if (res.success) {
      ElMessage.success(res.message)
    }
  } catch (e) {
    if (e !== 'cancel') {
      ElMessage.error('重建失败: ' + e.message)
    }
  } finally {
    rebuilding.value = false
  }
}

const loadSettings = async () => {
  try {
    const res = await apiFetch('/system/settings')
    if (res.success) {
      settings.value.dailyBudget = res.data.daily_budget || 0
    }
  } catch (e) {
    console.error('加载配置失败:', e)
  }
}

const saveSettings = async () => {
  try {
    const res = await apiFetch('/system/settings', {
      method: 'POST',
      body: JSON.stringify({
        daily_budget_cny: settings.value.dailyBudget
      })
    })
    if (res.success) {
      ElMessage.success('预算已保存')
    }
  } catch (e) {
    ElMessage.error('保存失败: ' + e.message)
  }
}

const loadStats = async () => {
  try {
    const res = await apiFetch('/admin/dashboard/stats')
    if (res.success) {
      stats.value = res.data
    }
  } catch (e) {
    console.error('加载统计数据失败:', e)
  }
}

const loadUsage = async () => {
  try {
    const res = await apiFetch('/usage/stats')
    if (res.success) {
      usageStats.value = res.data
    }
  } catch (e) {
    console.error('加载用量统计失败:', e)
  }
}

onMounted(() => {
  loadKnowledgeList()
  loadStats()
  loadUsage()
  loadSettings()
})
</script>

<style scoped>
.dashboard-page {
  padding: 20px;
  max-width: 1200px;
  margin: 0 auto;
}

.metric-cards {
  margin: 20px 0;
}

.metric-cards .el-card {
  text-align: center;
  padding: 20px 0;
}

.metric-icon {
  font-size: 32px;
  margin-bottom: 8px;
}

.metric-value {
  font-size: 28px;
  font-weight: bold;
  color: #409eff;
}

.metric-label {
  color: #666;
  margin-top: 8px;
  font-size: 14px;
}

.metric-sub {
  color: #999;
  font-size: 12px;
  margin-top: 4px;
}

.dashboard-tabs {
  margin-top: 20px;
}

.knowledge-toolbar {
  margin-bottom: 16px;
  display: flex;
  gap: 10px;
}

.form-tip {
  margin-left: 10px;
  color: #999;
  font-size: 12px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>