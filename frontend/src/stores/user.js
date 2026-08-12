import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { getToken, setToken, removeToken } from '@/utils/auth'
import { login as loginApi, register as registerApi, getCurrentUser } from '@/api/auth'

export const useUserStore = defineStore('user', () => {
  const token = ref(getToken() || '')
  const userInfo = ref(null)
  const loading = ref(false)

  const isLoggedIn = computed(() => !!token.value)

  // 【关键修复】兼容 role 和 is_admin 两种字段
  const isAdmin = computed(() => {
    return userInfo.value?.role === 'admin' || userInfo.value?.is_admin === true
  })

  const username = computed(() => userInfo.value?.username || '')

  const updateToken = (newToken) => {
    token.value = newToken
    setToken(newToken)
  }

  const login = async (credentials) => {
    loading.value = true
    try {
      const res = await loginApi(credentials)
      updateToken(res.access_token)
      await fetchUserInfo()
      return { success: true }
    } catch (error) {
      return {
        success: false,
        message: error.response?.data?.detail || '登录失败'
      }
    } finally {
      loading.value = false
    }
  }

  const register = async (data) => {
    loading.value = true
    try {
      await registerApi(data)
      return { success: true }
    } catch (error) {
      return {
        success: false,
        message: error.response?.data?.detail || '注册失败'
      }
    } finally {
      loading.value = false
    }
  }

  const fetchUserInfo = async () => {
    if (!token.value) {
      userInfo.value = null
      return
    }
    try {
      const res = await getCurrentUser()
      if (res.success && res.data) {
        userInfo.value = res.data
      } else {
        userInfo.value = null
      }
      return userInfo.value
    } catch (error) {
      console.error('获取用户信息失败:', error)
      userInfo.value = null
      if (error.response?.status === 401) {
        logout()
        window.location.href = '/login'
      }
      throw error
    }
  }

  const logout = () => {
    token.value = ''
    userInfo.value = null
    removeToken()
  }

  const init = async () => {
    if (token.value) {
      await fetchUserInfo()
    }
  }

  return {
    token,
    userInfo,
    loading,
    isLoggedIn,
    isAdmin,
    username,
    login,
    register,
    logout,
    fetchUserInfo,
    init,
    updateToken
  }
})