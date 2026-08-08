<template>
  <div class="login-container">
    <div class="login-box">
      <div class="logo">🤖</div>
      <h2>智扫通智能客服</h2>
      <p class="subtitle">{{ isLogin ? '用户登录' : '新用户注册' }}</p>

      <div class="form-group">
        <input
          v-model="username"
          placeholder="请输入用户名"
          @keyup.enter="handleSubmit"
        />
      </div>
      <div class="form-group">
        <input
          v-model="password"
          type="password"
          placeholder="请输入密码"
          @keyup.enter="handleSubmit"
        />
      </div>

      <div class="error-msg" v-if="errorMsg">{{ errorMsg }}</div>

      <button class="btn-primary" @click="handleSubmit" :disabled="loading">
        {{ loading ? '处理中...' : (isLogin ? '登 录' : '注 册') }}
      </button>

      <div class="switch-mode">
        <span @click="isLogin = !isLogin">
          {{ isLogin ? '没有账号？去注册' : '已有账号？去登录' }}
        </span>
      </div>

      <div class="guest-entry">
        <span @click="$emit('guest')">👤 暂不登录，以游客身份进入</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { login, register } from '../api/auth.js'

const emit = defineEmits(['login', 'guest'])

const username = ref('')
const password = ref('')
const isLogin = ref(true)
const loading = ref(false)
const errorMsg = ref('')

const handleSubmit = async () => {
  if (!username.value.trim() || !password.value.trim()) {
    errorMsg.value = '请输入用户名和密码'
    return
  }
  errorMsg.value = ''
  loading.value = true

  try {
    const api = isLogin.value ? login : register
    const data = await api(username.value.trim(), password.value.trim())

    if (data.access_token) {
      // 登录成功，保存 token
      localStorage.setItem('token', data.access_token)
      emit('login', data)
    } else if (data.detail) {
      errorMsg.value = data.detail
    } else {
      errorMsg.value = isLogin.value ? '登录失败' : '注册失败'
    }
  } catch (err) {
    errorMsg.value = '网络错误，请稍后重试'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-container {
  width: 100vw;
  height: 100vh;
  display: flex;
  justify-content: center;
  align-items: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}

.login-box {
  background: white;
  padding: 48px 40px;
  border-radius: 16px;
  width: 380px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
  text-align: center;
}

.logo {
  font-size: 48px;
  margin-bottom: 8px;
}

.login-box h2 {
  margin-bottom: 4px;
  color: #333;
  font-size: 22px;
}

.subtitle {
  color: #888;
  margin-bottom: 28px;
  font-size: 14px;
}

.form-group {
  margin-bottom: 16px;
}

.form-group input {
  width: 100%;
  padding: 12px 14px;
  border: 1px solid #ddd;
  border-radius: 8px;
  font-size: 14px;
  outline: none;
  transition: border-color 0.2s;
}

.form-group input:focus {
  border-color: #667eea;
}

.error-msg {
  color: #e74c3c;
  font-size: 13px;
  margin-bottom: 12px;
}

.btn-primary {
  width: 100%;
  padding: 12px;
  background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 15px;
  cursor: pointer;
  transition: opacity 0.2s;
}

.btn-primary:hover {
  opacity: 0.9;
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.switch-mode {
  margin-top: 18px;
  font-size: 13px;
  color: #667eea;
  cursor: pointer;
}

.switch-mode span:hover {
  text-decoration: underline;
}

.guest-entry {
  margin-top: 12px;
  font-size: 13px;
  color: #999;
  cursor: pointer;
}

.guest-entry span:hover {
  color: #667eea;
}
</style>