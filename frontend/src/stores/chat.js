import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { getToken } from '@/utils/auth'

const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8011/api'

// 内联 sendMessage，绕过 api/chat.js 的缓存问题
const sendMessageInline = (data, callbacks) => {
  return new Promise((resolve, reject) => {
    const { onSession, onMessage, onDone, onError } = callbacks
    const token = getToken()

    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${BASE_URL}/chat/send`)
    xhr.setRequestHeader('Content-Type', 'application/json')
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)

    let buffer = ''
    let lastLen = 0

    xhr.onprogress = () => {
      const newChunk = xhr.responseText.slice(lastLen)
      lastLen = xhr.responseText.length
      if (!newChunk) return

      buffer += newChunk

      // 解析 SSE
      const blocks = buffer.split('\n\n')
      buffer = blocks.pop() || ''

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

        if (eventType === 'session') onSession?.(content)
        else if (eventType === 'message') onMessage?.(content)
        else if (eventType === 'done') onDone?.()
        else if (eventType === 'error') onError?.(content)
      }
    }

    xhr.onload = () => {
      if (buffer.trim()) {
        const lines = buffer.split('\n')
        let eventType = 'message'
        const dataParts = []
        for (const line of lines) {
          if (line.startsWith('event:')) eventType = line.slice(6).trim()
          else if (line.startsWith('data:')) dataParts.push(line.slice(5).trimStart())
        }
        const content = dataParts.join('\n')
        if (eventType === 'message' && content) onMessage?.(content)
      }
      onDone?.()
      resolve()
    }

    xhr.onerror = () => {
      onError?.('网络请求失败')
      reject(new Error('网络请求失败'))
    }

    xhr.send(JSON.stringify(data))
  })
}

// 其他 API 保持简单
const apiGet = (url) => {
  const token = getToken()
  return fetch(`${BASE_URL}${url}`, {
    headers: token ? { 'Authorization': `Bearer ${token}` } : {}
  }).then(res => res.json())
}

const apiPost = (url, body) => {
  const token = getToken()
  return fetch(`${BASE_URL}${url}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': token ? `Bearer ${token}` : ''
    },
    body: JSON.stringify(body)
  }).then(res => res.json())
}

export const useChatStore = defineStore('chat', () => {
  const sessions = ref([])
  const currentSessionId = ref('')
  const messages = ref([])
  const isLoading = ref(false)
  const isStreaming = ref(false)

  const hasMessages = computed(() => messages.value.length > 0)

  const loadSessions = async () => {
    try {
      const res = await apiGet('/chat/sessions')
      sessions.value = res.sessions || []
    } catch (error) {
      console.error('加载会话列表失败:', error)
    }
  }

  const createNewSession = () => {
    currentSessionId.value = ''
    messages.value = []
  }

  const selectSession = async (sessionId) => {
    currentSessionId.value = sessionId
    if (sessionId) {
      try {
        const res = await apiGet(`/chat/history?session_id=${sessionId}`)
        messages.value = res.messages || []
      } catch (error) {
        console.error('加载历史记录失败:', error)
        messages.value = []
      }
    } else {
      messages.value = []
    }
  }

  const sendChatMessage = async (content) => {
    if (!content.trim()) return

    isLoading.value = true
    isStreaming.value = true

    // 创建新数组添加用户消息
    messages.value = [...messages.value, { role: 'user', content }]

    // 创建新数组添加 assistant 占位
    messages.value = [...messages.value, { role: 'assistant', content: '' }]
    const assistantIndex = messages.value.length - 1

    let fullText = ''

    try {
      await sendMessageInline(
        { message: content, session_id: currentSessionId.value },
        {
          onSession: (sessionId) => {
            currentSessionId.value = sessionId
          },
          onMessage: (chunk) => {
            fullText += chunk
            // 创建全新数组替换整个 messages，强制 Vue 响应式
            const newMessages = [...messages.value]
            newMessages[assistantIndex] = {
              role: 'assistant',
              content: fullText
            }
            messages.value = newMessages
          },
          onDone: () => {
            isStreaming.value = false
            isLoading.value = false
            loadSessions()
          },
          onError: (error) => {
            isStreaming.value = false
            isLoading.value = false
            const newMessages = [...messages.value]
            newMessages[assistantIndex] = {
              role: 'assistant',
              content: `❌ 出错了：${error}`
            }
            messages.value = newMessages
          }
        }
      )
    } catch (error) {
      isStreaming.value = false
      isLoading.value = false
      const newMessages = [...messages.value]
      newMessages[assistantIndex] = {
        role: 'assistant',
        content: `❌ 请求失败：${error.message}`
      }
      messages.value = newMessages
    }
  }

  const clearCurrentSession = async () => {
    if (!currentSessionId.value) {
      messages.value = []
      return
    }
    try {
      await apiPost('/chat/clear', { session_id: currentSessionId.value })
      messages.value = []
      await loadSessions()
    } catch (error) {
      console.error('清空会话失败:', error)
    }
  }

  return {
    sessions,
    currentSessionId,
    messages,
    isLoading,
    isStreaming,
    hasMessages,
    loadSessions,
    createNewSession,
    selectSession,
    sendChatMessage,
    clearCurrentSession
  }
})