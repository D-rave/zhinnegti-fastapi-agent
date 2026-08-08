import { getToken } from '@/utils/auth'

const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8011/api'

export const sendMessage = async (data, callbacks) => {
  const { onSession, onMessage, onDone, onError } = callbacks
  const token = getToken()

  const response = await fetch(`${BASE_URL}/chat/send`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': token ? `Bearer ${token}` : ''
    },
    body: JSON.stringify(data)
  })

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`)
  }

  // 【关键】先拿到完整文本，再解析 SSE（避免流式解析的兼容性问题）
  const text = await response.text()

  // 按 \n\n 分割事件块
  const blocks = text.split('\n\n')

  for (const block of blocks) {
    if (!block.trim()) continue

    const lines = block.split('\n')
    let eventType = 'message'
    const dataParts = []

    for (const line of lines) {
      if (line.startsWith('event:')) {
        eventType = line.slice(6).trim()
      } else if (line.startsWith('data:')) {
        dataParts.push(line.slice(5).trimStart())
      }
    }

    const content = dataParts.join('\n')

    if (eventType === 'session') {
      onSession?.(content)
    } else if (eventType === 'message') {
      onMessage?.(content)
    } else if (eventType === 'done') {
      onDone?.()
    } else if (eventType === 'error') {
      onError?.(content)
    }
  }

  // 确保 onDone 被调用
  onDone?.()
}

export const getHistory = (sessionId) => {
  const token = getToken()
  return fetch(`${BASE_URL}/chat/history?session_id=${sessionId}`, {
    headers: token ? { 'Authorization': `Bearer ${token}` } : {}
  }).then(res => res.json())
}

export const getSessions = () => {
  const token = getToken()
  return fetch(`${BASE_URL}/chat/sessions`, {
    headers: token ? { 'Authorization': `Bearer ${token}` } : {}
  }).then(res => res.json())
}

export const clearSession = (sessionId) => {
  const token = getToken()
  return fetch(`${BASE_URL}/chat/clear`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': token ? `Bearer ${token}` : ''
    },
    body: JSON.stringify({ session_id: sessionId })
  }).then(res => res.json())
}