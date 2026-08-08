<template>
  <div class="admin-page">
    <el-page-header @back="router.back()" title="管理后台" />

    <el-tabs v-model="activeTab" class="admin-tabs">
      <!-- 用户管理 -->
      <el-tab-pane label="用户管理" name="users">
        <el-table :data="userList" v-loading="loading" border>
          <el-table-column prop="id" label="ID" width="80" />
          <el-table-column prop="username" label="用户名" />
          <el-table-column prop="email" label="邮箱" />
          <el-table-column prop="is_active" label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="row.is_active ? 'success' : 'danger'">
                {{ row.is_active ? '正常' : '禁用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="created_at" label="注册时间" />
        </el-table>
      </el-tab-pane>

      <!-- 知识库管理 -->
      <el-tab-pane label="知识库" name="knowledge">
        <el-upload
          drag
          action="/api/admin/knowledge/upload"
          :headers="uploadHeaders"
          accept=".pdf,.txt,.docx"
          :on-success="handleUploadSuccess"
          :on-error="handleUploadError"
        >
          <el-icon class="el-icon--upload"><Upload /></el-icon>
          <div class="el-upload__text">拖拽文件到此处或 <em>点击上传</em></div>
          <template #tip>
            <div class="el-upload__tip">支持 PDF、TXT、DOCX 格式</div>
          </template>
        </el-upload>

        <el-table :data="knowledgeList" class="knowledge-table" border>
          <el-table-column prop="filename" label="文件名" />
          <el-table-column prop="size" label="大小" width="120" />
          <el-table-column prop="uploaded_at" label="上传时间" />
          <el-table-column label="操作" width="120">
            <template #default="{ row }">
              <el-button type="danger" size="small" @click="deleteKnowledge(row.id)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 系统配置 -->
      <el-tab-pane label="系统配置" name="settings">
        <el-form :model="settings" label-width="120px">
          <el-form-item label="系统提示词">
            <el-input v-model="settings.systemPrompt" type="textarea" :rows="6" />
          </el-form-item>
          <el-form-item label="Temperature">
            <el-slider v-model="settings.temperature" :min="0" :max="2" :step="0.1" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="saveSettings">保存配置</el-button>
          </el-form-item>
        </el-form>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { ElMessage } from 'element-plus'
import { Upload } from '@element-plus/icons-vue'

const router = useRouter()
const userStore = useUserStore()

const activeTab = ref('users')
const loading = ref(false)
const userList = ref([])
const knowledgeList = ref([])
const settings = ref({
  systemPrompt: '',
  temperature: 0.7
})

const uploadHeaders = computed(() => ({
  Authorization: `Bearer ${userStore.token}`
}))

const handleUploadSuccess = () => {
  ElMessage.success('上传成功')
  loadKnowledgeList()
}

const handleUploadError = () => {
  ElMessage.error('上传失败')
}

const deleteKnowledge = async (id) => {
  // TODO: 调用删除 API
  ElMessage.success('删除成功')
}

const saveSettings = async () => {
  // TODO: 调用保存配置 API
  ElMessage.success('配置已保存')
}

const loadUsers = async () => {
  loading.value = true
  // TODO: 调用获取用户列表 API
  loading.value = false
}

const loadKnowledgeList = async () => {
  // TODO: 调用获取知识库列表 API
}

onMounted(() => {
  loadUsers()
  loadKnowledgeList()
})
</script>

<style scoped>
.admin-page {
  padding: 20px;
  max-width: 1200px;
  margin: 0 auto;
}

.admin-tabs {
  margin-top: 20px;
}

.knowledge-table {
  margin-top: 20px;
}
</style>