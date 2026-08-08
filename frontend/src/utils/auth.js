/**
 * Token 工具（独立文件，不依赖 Pinia）
 * 供 axios 拦截器、SSE 请求等普通 JS 文件使用
 */
import Cookies from 'js-cookie'

const TOKEN_KEY = 'access_token'

export const getToken = () => {
  return Cookies.get(TOKEN_KEY) || ''
}

export const setToken = (token) => {
  if (token) {
    Cookies.set(TOKEN_KEY, token, { expires: 1 }) // 1天
  } else {
    Cookies.remove(TOKEN_KEY)
  }
}

export const removeToken = () => {
  Cookies.remove(TOKEN_KEY)
}

export const hasToken = () => {
  return !!getToken()
}