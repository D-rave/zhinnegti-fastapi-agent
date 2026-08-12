// frontend/src/stores/chat.js
import { defineStore } from 'pinia'
import { ref, computed, nextTick } from 'vue'
import { useUserStore } from './user'

const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8011/api'

const apiFetch = async (url, options = {}) => {
  const userStore = useUserStore()
  const token = userStore.token

  const headers = {
    ...options.headers,
    'Authorization': token ? `Bearer ${token}` : ''
  }

  if (options.body && !(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json'
  }

  const res = await fetch(`${BASE_URL}${url}`, {
    ...options,
    headers
  })

  if (res.status === 401) {
    userStore.logout()
    window.location.href = '/login'
    throw new Error('登录已过期，请重新登录')
  }

  return res.json()
}

// ==================== 增量 SSE 解析（修复重复输出 + onDone 防重）====================
const sendMessageInline = (data, callbacks) => {
  return new Promise((resolve, reject) => {
    const { onSession, onMessage, onDone, onError } = callbacks
    const userStore = useUserStore()
    const token = userStore.token

    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${BASE_URL}/chat/send`)
    xhr.setRequestHeader('Content-Type', 'application/json')
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)

    let lastLen = 0
    let sseBuffer = ''      // 缓存不完整的 SSE 数据
    let messageCount = 0
    let sessionReceived = false
    let doneCalled = false   // 【新增】防重标记

    // 【新增】安全的 onDone 调用，防止重复触发
    const safeOnDone = () => {
      if (!doneCalled) {
        doneCalled = true
        onDone?.()
      }
    }

    // 解析并处理一个 SSE 事件块
    const processBlock = (block) => {
      const lines = block.split('\n')
      let eventType = 'message'
      const dataParts = []

      for (const rawLine of lines) {
        const line = rawLine.trim()
        if (!line) continue
        if (line.startsWith('event:')) {
          eventType = line.slice(6).trim()
        } else if (line.startsWith('data:')) {
          dataParts.push(line.slice(5).trimStart())
        }
      }

      const content = dataParts.join('\n')

      if (eventType === 'session') {
        sessionReceived = true
        onSession?.(content)
      } else if (eventType === 'message' && content) {
        messageCount++
        onMessage?.(content)
      } else if (eventType === 'done') {
        safeOnDone()   // 【改】用防重版本
      } else if (eventType === 'error') {
        onError?.(content)
      }
    }

    // 从 buffer 中提取完整事件（以 \n\n 结尾）并处理
    const flushBuffer = (isFinal = false) => {
      // 统一换行符
      let text = sseBuffer.replace(/\r\n/g, '\n').replace(/\r/g, '\n')

      if (isFinal) {
        // 最终处理：剩余所有内容都强制解析
        const blocks = text.split(/\n\n+/)
        for (const block of blocks) {
          if (block.trim()) processBlock(block.trim())
        }
        sseBuffer = ''
        return
      }

      // 只处理以 \n\n 结尾的完整事件
      const blocks = text.split('\n\n')
      // 最后一个块可能不完整，保留到 buffer
      sseBuffer = blocks.pop() || ''

      for (const block of blocks) {
        if (block.trim()) processBlock(block.trim())
      }
    }

    xhr.onprogress = () => {
      const currentLen = xhr.responseText.length
      if (currentLen > lastLen) {
        // 只取新增字节，追加到 buffer
        const newText = xhr.responseText.slice(lastLen, currentLen)
        lastLen = currentLen
        sseBuffer += newText
        flushBuffer(false)
      }
    }

    xhr.onload = () => {
      const fullText = xhr.responseText
      console.log(`[SSE] onload 触发, responseText 总长度: ${fullText.length}`)

      // 把最后剩余的字节补进 buffer
      const remaining = fullText.slice(lastLen)
      if (remaining) {
        sseBuffer += remaining
        lastLen = fullText.length
      }
      flushBuffer(true)

      console.log(`[SSE] 请求完成, session=${sessionReceived}, 共 ${messageCount} 条 message`)

      // 兜底：如果没有任何事件被解析，尝试备用解析
      if (!sessionReceived && messageCount === 0 && fullText.length > 0) {
        console.warn('[SSE] 警告: 没有解析到任何事件，尝试备用解析...')
        const lines = fullText.split('\n')
        for (const line of lines) {
          const trimmed = line.trim()
          if (trimmed.startsWith('data:')) {
            const content = trimmed.slice(5).trimStart()
            if (content) {
              messageCount++
              onMessage?.(content)
            }
          }
        }
      }

      safeOnDone()   // 【改】用防重版本
      resolve()
    }

    xhr.onerror = () => {
      console.error('[SSE] 网络请求失败')
      onError?.('网络请求失败')
      reject(new Error('网络请求失败'))
    }

    xhr.ontimeout = () => {
      console.error('[SSE] 请求超时')
      onError?.('请求超时')
      reject(new Error('请求超时'))
    }

    xhr.send(JSON.stringify(data))
  })
}

export const useChatStore = defineStore('chat', () => {
  const sessions = ref([])
  const currentSessionId = ref('')
  const messages = ref([])
  const isLoading = ref(false)
  const isStreaming = ref(false)
  const isSending = ref(false)

  const hasMessages = computed(() => messages.value.length > 0)

  const loadSessions = async () => {
    try {
      const res = await apiFetch('/chat/sessions')
      sessions.value = res.sessions || []
    } catch (error) {
      console.error('加载会话列表失败:', error)
    }
  }

  const createNewSession = () => {
    if (isSending.value) {
      console.warn('[Chat] 发送中，禁止新建会话')
      return
    }
    currentSessionId.value = ''
    messages.value = []
  }

  const selectSession = async (sessionId) => {
    if (isSending.value) {
      console.warn('[Chat] 发送中，禁止切换会话')
      return
    }
    currentSessionId.value = sessionId
    if (sessionId) {
      try {
        const res = await apiFetch(`/chat/history?session_id=${sessionId}`)
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
    if (isSending.value) {
      console.warn('[Chat] 已有消息正在发送，请等待')
      return
    }

    isSending.value = true
    isLoading.value = true
    isStreaming.value = true

    messages.value = [...messages.value, { role: 'user', content }]
    await nextTick()

    messages.value = [...messages.value, { role: 'assistant', content: '' }]
    const assistantIndex = messages.value.length - 1
    await nextTick()

    let fullText = ''
    let receivedAny = false

    try {
      await sendMessageInline(
        { message: content, session_id: currentSessionId.value },
        {
          onSession: (sessionId) => {
            console.log(`[Chat] session 事件: ${sessionId}`)
            currentSessionId.value = sessionId
          },
          onMessage: (chunk) => {
            receivedAny = true
            fullText += chunk
            console.log(`[Chat] 收到 chunk, 当前总长度: ${fullText.length}`)

            const newMessages = [...messages.value]
            newMessages[assistantIndex] = {
              role: 'assistant',
              content: fullText
            }
            messages.value = newMessages
          },
          onDone: () => {
            console.log(`[Chat] 流式完成, 总长度: ${fullText.length}, 收到事件: ${receivedAny}`)
            isStreaming.value = false
            isLoading.value = false
            isSending.value = false
            loadSessions()
          },
          onError: (error) => {
            console.error(`[Chat] 流式错误: ${error}`)
            isStreaming.value = false
            isLoading.value = false
            isSending.value = false
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
      console.error(`[Chat] 请求异常: ${error.message}`)
      isStreaming.value = false
      isLoading.value = false
      isSending.value = false
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
      await apiFetch('/chat/clear', {
        method: 'POST',
        body: JSON.stringify({ session_id: currentSessionId.value })
      })
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
    isSending,
    hasMessages,
    loadSessions,
    createNewSession,
    selectSession,
    sendChatMessage,
    clearCurrentSession
  }
})