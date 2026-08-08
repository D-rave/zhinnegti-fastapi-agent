import axios from 'axios'
import { getToken } from '@/utils/auth'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8011/api',
  timeout: 10000
})

// 请求拦截器：自动添加 Token
api.interceptors.request.use(
  (config) => {
    const token = getToken()
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// 响应拦截器：处理 401 未授权
api.interceptors.response.use(
  (response) => response.data,
  (error) => {
    if (error.response?.status === 401) {
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

// 登录：JSON 格式
export const login = (data) => api.post('/auth/login', data)

export const register = (data) => api.post('/auth/register', data)
export const getCurrentUser = () => api.get('/auth/me')

export default api