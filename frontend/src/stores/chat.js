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

// ==================== 【关键修复】超健壮 SSE 解析 ====================
const parseSSEEvents = (text) => {
  /**
   * 解析 SSE 文本为事件数组
   * 兼容：\n\n 分隔、\r\n\r\n 分隔、多余空行、多行 data
   */
  if (!text || !text.trim()) return []

  // 统一换行符为 \n
  const normalized = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n')

  // 按 \n\n 分割事件块（兼容多个连续空行）
  const rawBlocks = normalized.split(/\n\n+/)
  const events = []

  for (const rawBlock of rawBlocks) {
    const block = rawBlock.trim()
    if (!block) continue

    const lines = block.split('\n')
    let eventType = 'message'
    const dataParts = []

    for (const rawLine of lines) {
      const line = rawLine.trim()
      if (!line) continue

      if (line.startsWith('event:')) {
        eventType = line.slice(6).trim()
      } else if (line.startsWith('data:')) {
        // data: 后面可能有一个空格，也可能没有
        dataParts.push(line.slice(5).trimStart())
      }
    }

    // 只收集有 data 或特殊事件类型的
    if (dataParts.length > 0 || ['session', 'done', 'error'].includes(eventType)) {
      events.push({ eventType, content: dataParts.join('\n') })
    }
  }

  return events
}

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
    let messageCount = 0
    let sessionReceived = false
    let processedTextLen = 0  // 记录已处理到的位置，避免重复处理

    // 处理新增文本中的 SSE 事件
    const processNewText = (fullText, isFinal = false) => {
      // 只处理新增部分
      const newText = fullText.slice(processedTextLen)
      if (!newText.trim()) return

      const events = parseSSEEvents(newText)
      console.log(`[SSE] 解析到 ${events.length} 个事件 (新增 ${newText.length} 字节)`)

      for (const { eventType, content } of events) {
        console.log(`[SSE] 事件: type=${eventType}, len=${content?.length || 0}, content=${content?.slice(0, 30)}`)

        if (eventType === 'session') {
          sessionReceived = true
          onSession?.(content)
        }
        else if (eventType === 'message' && content) {
          messageCount++
          onMessage?.(content)
        }
        else if (eventType === 'done') {
          onDone?.()
        }
        else if (eventType === 'error') {
          onError?.(content)
        }
      }

      // 更新已处理位置（如果不是最终处理，留一点缓冲给不完整的块）
      if (isFinal) {
        processedTextLen = fullText.length
      } else {
        // 找到最后一个完整 \n\n 的位置
        const lastDoubleNewline = fullText.lastIndexOf('\n\n')
        if (lastDoubleNewline > processedTextLen) {
          processedTextLen = lastDoubleNewline + 2
        }
      }
    }

    xhr.onprogress = () => {
      const currentLen = xhr.responseText.length
      if (currentLen > lastLen) {
        lastLen = currentLen
        processNewText(xhr.responseText, false)
      }
    }

    xhr.onload = () => {
      const fullText = xhr.responseText
      console.log(`[SSE] onload 触发, responseText 总长度: ${fullText.length}`)
      console.log(`[SSE] 原始内容前200字: ${fullText.slice(0, 200)}`)

      // 最终处理：解析全部文本
      processNewText(fullText, true)

      console.log(`[SSE] 请求完成, session=${sessionReceived}, 共 ${messageCount} 条 message`)

      // 如果还没触发 done，补一个
      if (!sessionReceived && messageCount === 0 && fullText.length > 0) {
        console.warn('[SSE] 警告: 没有解析到任何事件，尝试备用解析...')
        // 备用：直接按行查找 data:
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

      onDone?.()
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