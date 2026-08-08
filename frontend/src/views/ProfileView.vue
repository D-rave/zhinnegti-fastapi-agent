<template>
  <div class="profile-page">
    <el-page-header @back="router.back()" title="个人中心" />

    <el-card class="profile-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span>基本信息</span>
          <el-button type="primary" size="small" @click="showPasswordDialog = true">
            修改密码
          </el-button>
        </div>
      </template>

      <el-descriptions :column="1" border v-loading="userStore.loading">
        <el-descriptions-item label="用户ID">
          {{ userStore.userInfo?.id || '-' }}
        </el-descriptions-item>
        <el-descriptions-item label="用户名">
          {{ userStore.userInfo?.username || '-' }}
        </el-descriptions-item>
        <el-descriptions-item label="账号状态">
          <el-tag :type="userStore.userInfo?.is_active ? 'success' : 'danger'">
            {{ userStore.userInfo?.is_active ? '正常' : '已禁用' }}
          </el-tag>
        </el-descriptions-item>
      </el-descriptions>
    </el-card>

    <!-- 修改密码对话框 -->
    <el-dialog v-model="showPasswordDialog" title="修改密码" width="400px">
      <el-form :model="passwordForm" :rules="passwordRules" ref="passwordRef">
        <el-form-item prop="oldPassword" label="原密码">
          <el-input v-model="passwordForm.oldPassword" type="password" show-password />
        </el-form-item>
        <el-form-item prop="newPassword" label="新密码">
          <el-input v-model="passwordForm.newPassword" type="password" show-password />
        </el-form-item>
        <el-form-item prop="confirmPassword" label="确认密码">
          <el-input v-model="passwordForm.confirmPassword" type="password" show-password />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showPasswordDialog = false">取消</el-button>
        <el-button type="primary" @click="handleChangePassword" :loading="passwordLoading">
          确认
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { ElMessage } from 'element-plus'

const router = useRouter()
const userStore = useUserStore()

// 进入页面时获取用户信息
onMounted(async () => {
  try {
    await userStore.fetchUserInfo()
  } catch (error) {
    // 401 会自动跳转登录页（axios 拦截器已处理）
    console.error('获取用户信息失败:', error)
  }
})

// 修改密码
const showPasswordDialog = ref(false)
const passwordLoading = ref(false)
const passwordRef = ref(null)
const passwordForm = ref({
  oldPassword: '',
  newPassword: '',
  confirmPassword: ''
})

const validateConfirm = (rule, value, callback) => {
  if (value !== passwordForm.value.newPassword) {
    callback(new Error('两次密码不一致'))
  } else {
    callback()
  }
}

const passwordRules = {
  oldPassword: [{ required: true, message: '请输入原密码', trigger: 'blur' }],
  newPassword: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, message: '密码至少6位', trigger: 'blur' }
  ],
  confirmPassword: [
    { required: true, message: '请确认密码', trigger: 'blur' },
    { validator: validateConfirm, trigger: 'blur' }
  ]
}

const handleChangePassword = async () => {
  const valid = await passwordRef.value.validate().catch(() => false)
  if (!valid) return

  passwordLoading.value = true
  try {
    // TODO: 调用后端修改密码 API
    ElMessage.success('密码修改成功')
    showPasswordDialog.value = false
    passwordForm.value = { oldPassword: '', newPassword: '', confirmPassword: '' }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '修改失败')
  } finally {
    passwordLoading.value = false
  }
}
</script>

<style scoped>
.profile-page {
  padding: 20px;
  max-width: 800px;
  margin: 0 auto;
}

.profile-card {
  margin-top: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>