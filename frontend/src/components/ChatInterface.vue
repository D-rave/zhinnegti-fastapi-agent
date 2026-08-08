<template>
  <div class="chat-app">
    <!-- 左侧边栏 -->
    <aside class="sidebar" :class="{ collapsed: sidebarCollapsed }">
      <div class="sidebar-header">
        <div class="logo" @click="createNewSession">
          <span class="logo-icon">🤖</span>
          <span class="logo-text" v-if="!sidebarCollapsed">智扫通</span>
        </div>
        <button class="new-chat-btn" @click="createNewSession" title="新对话">
          <span>+</span>
          <span v-if="!sidebarCollapsed">新对话</span>
        </button>
      </div>

      <div class="session-list" v-if="!sidebarCollapsed">
        <div class="session-group-title">历史会话</div>
        <div
          v-for="s in sessions"
          :key="s.session_id"
          :class="['session-item', s.session_id === sessionId ? 'active' : '']"
          @click="switchSession(s.session_id)"
          :title="s.title || '新对话'"
        >
          <span class="session-icon">💬</span>
          <span class="session-title">{{ s.title || '新对话' }}</span>
        </div>
        <div v-if="sessions.length === 0" class="empty-tip">暂无历史会话</div>
      </div>

      <div class="sidebar-footer" v-if="!sidebarCollapsed">
        <div class="user-info">
          <span class="user-avatar">👤</span>
          <span class="user-name">已登录</span>
        </div>
        <button class="logout-btn" @click="$emit('logout')">退出</button>
      </div>
    </aside>

    <!-- 主内容区 -->
    <main class="main-content">
      <header class="top-bar">
        <button class="toggle-sidebar" @click="sidebarCollapsed = !sidebarCollapsed">
          {{ sidebarCollapsed ? '→' : '←' }}
        </button>
        <div class="top-title">
          <span v-if="currentSessionTitle">{{ currentSessionTitle }}</span>
          <span v-else>新对话</span>
        </div>
        <div class="top-actions">
          <button class="action-btn" @click="clearConversation" :disabled="loading" title="清空当前会话">
            🗑️
          </button>
        </div>
      </header>

      <!-- 消息区域 -->
      <div class="messages-area" ref="messagesRef">
        <!-- 欢迎语（新会话时显示） -->
        <div v-if="showWelcome" class="welcome-screen">
          <div class="welcome-icon">🤖</div>
          <h1>智扫通智能客服</h1>
          <p>基于 ReAct Agent + RAG 的智能客服系统</p>
          <div class="quick-actions">
            <button class="quick-btn" @click="quickSend('长沙哪里有扫地机器人卖？')">🔍 长沙扫地机器人店铺</button>
            <button class="quick-btn" @click="quickSend('查一下北京今天的天气')">🌤️ 北京天气查询</button>
            <button class="quick-btn" @click="quickSend('推荐一款性价比高的扫地机器人')">⭐ 产品推荐</button>
            <button class="quick-btn" @click="quickSend('扫地机器人怎么保养？')">🔧 保养指南</button>
          </div>
        </div>

        <!-- 消息列表 -->
        <template v-else>
          <div
            v-for="(msg, index) in messages"
            :key="msg.id"
            :class="['message-row', msg.role]"
          >
            <div class="message-avatar">
              {{ msg.role === 'user' ? '👤' : '🤖' }}
            </div>
            <div class="message-body">
              <div class="message-header">
                <span class="message-role">{{ msg.role === 'user' ? '用户' : 'AI助手' }}</span>
                <span class="message-time">{{ formatTime(msg.time) }}</span>
              </div>
              <!-- 关键修复：先不用 marked，直接显示纯文本，排除 marked 问题 -->
              <div class="message-content" v-html="renderMarkdown(msg.content)"></div>
            </div>
          </div>
        </template>

        <!-- 加载中 -->
        <div v-if="loading" class="message-row assistant">
          <div class="message-avatar">🤖</div>
          <div class="message-body">
            <div class="message-header">
              <span class="message-role">AI助手</span>
            </div>
            <div class="typing-indicator">
              <span></span><span></span><span></span>
            </div>
          </div>
        </div>
      </div>

      <!-- 输入区域 -->
      <div class="input-area">
        <div class="input-wrapper">
          <textarea
            v-model="inputMessage"
            @keydown.enter.prevent="handleEnter"
            placeholder="请输入您的问题，按 Enter 发送..."
            :disabled="loading"
            rows="1"
            ref="inputRef"
          ></textarea>
          <button
            class="send-btn"
            @click="sendMessage"
            :disabled="!inputMessage.trim() || loading"
          >
            <span v-if="!loading">➤</span>
            <span v-else>⏹</span>
          </button>
        </div>
        <div class="input-hint">
          <span>按 Enter 发送，Shift + Enter 换行</span>
          <span v-if="loading" class="stop-hint" @click="stopGeneration">点击停止生成</span>
        </div>
      </div>
    </main>
  </div>
</template>

<script setup>
import { marked } from 'marked'
import { ref, nextTick, onMounted, watch, computed } from 'vue'
import { getHistory, getSessions, clearChat } from '../api/chat.js'

const props = defineProps({
  token: { type: String, default: '' },
  isGuest: { type: Boolean, default: false },
})
const emit = defineEmits(['logout'])

const messages = ref([])
const inputMessage = ref('')
const loading = ref(false)
const sessionId = ref('')
const sessions = ref([])
const messagesRef = ref(null)
const inputRef = ref(null)
const abortController = ref(null)
const sidebarCollapsed = ref(false)

const currentSessionTitle = computed(() => {
  const s = sessions.value.find(s => s.session_id === sessionId.value)
  return s?.title || ''
})

const showWelcome = computed(() => messages.value.length === 0)

const SESSION_KEY = 'zhinengti_current_session'
const saveSession = () => { if (sessionId.value) localStorage.setItem(SESSION_KEY, sessionId.value) }
const loadSession = () => {
  const saved = localStorage.getItem(SESSION_KEY)
  if (saved) { sessionId.value = saved; return true }
  return false
}
// ========== Markdown 渲染 ==========
marked.setOptions({
  breaks: true,
  gfm: true,
  headerIds: false,
  mangle: false,
  async: false  // 强制同步，防止返回 Promise
})
const renderMarkdown = (text) => {
  if (!text) return ''
  try {
    const result = marked.parse(text)
    // 防御：如果 marked 还是返回 Promise，降级为纯文本
    if (result && typeof result.then === 'function') {
      return text.replace(/\n/g, '<br>')
    }
    return result
  } catch (e) {
    return text.replace(/\n/g, '<br>')
  }
}
const formatTime = (time) => {
  if (!time) return ''
  const d = new Date(time)
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

const scrollToBottom = async () => {
  await nextTick()
  if (messagesRef.value) messagesRef.value.scrollTop = messagesRef.value.scrollHeight
}

const getHeaders = () => {
  const h = { 'Content-Type': 'application/json' }
  if (props.token) h['Authorization'] = `Bearer ${props.token}`
  return h
}

const quickSend = (text) => { inputMessage.value = text; sendMessage() }
const handleEnter = (e) => { if (!e.shiftKey) sendMessage() }

// 核心修复：直接修改 content，并强制触发 Vue 响应式更新
const appendToAiMessage = (index, text) => {
  const msg = messages.value[index]
  if (!msg) {
    console.error('[前端] 索引越界:', index, '数组长度:', messages.value.length)
    return
  }
  msg.content += text
  // 防御性：强制触发数组更新，确保 Vue 检测到变化
  messages.value = [...messages.value]
  console.log('[前端] 追加内容，当前总长度:', msg.content.length, '本次追加:', JSON.stringify(text.substring(0, 30)))
}

const setAiMessage = (index, text) => {
  const msg = messages.value[index]
  if (!msg) return
  msg.content = text
  messages.value = [...messages.value]
}

const generateUUID = () => 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
  const r = Math.random() * 16 | 0
  return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16)
})

const sendMessage = async () => {
  const text = inputMessage.value.trim()
  if (!text || loading.value) return

  if (!sessionId.value) {
    sessionId.value = generateUUID()
    saveSession()
    sessions.value.unshift({
      session_id: sessionId.value,
      title: text.slice(0, 20) + (text.length > 20 ? '...' : ''),
      created_at: new Date().toISOString()
    })
  }

  abortController.value = new AbortController()

  messages.value.push({
    id: 'user-' + Date.now(),
    role: 'user',
    content: text,
    time: new Date().toISOString()
  })
  inputMessage.value = ''
  loading.value = true
  await scrollToBottom()

  const aiMsgIndex = messages.value.length
  messages.value.push({
    id: 'ai-' + Date.now(),
    role: 'assistant',
    content: '',
    time: new Date().toISOString()
  })
  await scrollToBottom()
  console.log('[前端] AI 占位索引:', aiMsgIndex, '当前消息数:', messages.value.length)

  try {
    const response = await fetch('/api/chat/send', {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify({ message: text, session_id: sessionId.value }),
      signal: abortController.value.signal,
    })

    console.log('[前端] 响应状态:', response.status, 'Content-Type:', response.headers.get('content-type'))

    const contentType = response.headers.get('content-type') || ''
    const isSSE = contentType.includes('text/event-stream')

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      const decoded = decoder.decode(value, { stream: true })
      console.log('[前端] 收到原始数据:', JSON.stringify(decoded))
      buffer += decoded

      if (isSSE) {
        buffer = parseSSEBuffer(buffer, aiMsgIndex)
      } else {
        appendToAiMessage(aiMsgIndex, decoded)
        await scrollToBottom()
      }
    }

    if (isSSE && buffer.trim()) {
      console.log('[前端] 处理剩余 buffer:', JSON.stringify(buffer))
      parseSSERemaining(buffer, aiMsgIndex)
    }

    loading.value = false
    await scrollToBottom()
    if (!props.isGuest) await loadSessionList()

  } catch (err) {
    console.error('[前端] 请求异常:', err)
    if (err.name === 'AbortError') {
      appendToAiMessage(aiMsgIndex, '\n\n*[用户已停止生成]*')
    } else {
      setAiMessage(aiMsgIndex, '发送失败：' + (err.message || '网络错误'))
    }
    loading.value = false
    await scrollToBottom()
  }
}

// ========== SSE 解析（关键修复：标准化换行符，兼容 \r\n）==========
const parseSSEBuffer = (buffer, aiMsgIndex) => {
  const normalized = buffer.replace(/\r\n/g, '\n').replace(/\r/g, '\n')
  const parts = normalized.split('\n\n')   // ← 只用这一套
  const remaining = parts.pop()             // 最后一个可能不完整，留到下次

  for (const eventStr of parts) {
    if (eventStr.trim()) processSSEEvent(eventStr, aiMsgIndex)
  }

  return remaining
}

const processSSEEvent = (eventStr, aiMsgIndex) => {
  console.log('[前端] 解析事件:', JSON.stringify(eventStr))
  let eventType = 'message'
  const dataLines = []

  for (const line of eventStr.split('\n')) {
    const trimmed = line.trim()
    if (trimmed.startsWith('event:')) {
      eventType = trimmed.slice(6).trim()
    } else if (trimmed.startsWith('data:')) {
      dataLines.push(trimmed.slice(5).trim())
    }
  }

  if (dataLines.length === 0) {
    console.log('[前端] 事件无 data 字段')
    return
  }

  const data = dataLines.join('\n')
  console.log('[前端] 事件类型:', eventType, '数据长度:', data.length, '数据:', JSON.stringify(data.substring(0, 50)))
  applyEventData(eventType, data, aiMsgIndex)
}

const parseSSERemaining = (buffer, aiMsgIndex) => {
  const normalized = buffer.replace(/\r\n/g, '\n').replace(/\r/g, '\n')
  const events = normalized.split('\n\n')
  for (const eventStr of events) {
    if (eventStr.trim()) processSSEEvent(eventStr, aiMsgIndex)
  }
}
const applyEventData = (eventType, data, aiMsgIndex) => {
  if (eventType === 'session') {
    if (data) { sessionId.value = data; saveSession() }
  } else if (eventType === 'message') {
    appendToAiMessage(aiMsgIndex, data)
    scrollToBottom()
  } else if (eventType === 'done') {
    console.log('[前端] 收到 done 事件')
    loading.value = false
  } else if (eventType === 'error') {
    setAiMessage(aiMsgIndex, '出错了：' + data)
    loading.value = false
  }
}

const stopGeneration = () => {
  if (abortController.value) { abortController.value.abort(); abortController.value = null }
  loading.value = false
}

const createNewSession = () => {
  if (loading.value) return
  sessionId.value = generateUUID()
  saveSession()
  messages.value = []
  sessions.value.unshift({ session_id: sessionId.value, title: '新对话', created_at: new Date().toISOString() })
  nextTick(() => { if (inputRef.value) inputRef.value.focus() })
}

const loadSessionList = async () => {
  if (props.isGuest || !props.token) return
  try {
    const res = await getSessions(props.token)
    if (res.sessions && Array.isArray(res.sessions)) sessions.value = res.sessions
    else if (res.data && Array.isArray(res.data)) sessions.value = res.data
  } catch (e) { console.error('加载会话列表失败', e) }
}

const switchSession = async (sid) => {
  if (loading.value || sid === sessionId.value) return
  if (sessionId.value && messages.value.length > 0) saveSession()
  sessionId.value = sid
  saveSession()
  messages.value = []
  loading.value = true
  try {
    const res = await getHistory(sid, props.token)
    let msgs = []
    if (res.messages && Array.isArray(res.messages)) msgs = res.messages
    else if (res.data && res.data.messages) msgs = res.data.messages
    if (msgs.length > 0) {
      messages.value = msgs.map((m, idx) => ({
        id: m.id || `${sid}-${idx}`, role: m.role, content: m.content,
        time: m.created_at || new Date().toISOString()
      }))
    }
  } catch (e) { console.error('加载历史失败', e) }
  finally { loading.value = false; await scrollToBottom() }
}

const clearConversation = async () => {
  if (loading.value) return
  if (!sessionId.value) { messages.value = []; return }
  if (!confirm('确定要清空当前会话的所有消息吗？')) return
  try {
    await clearChat(sessionId.value, props.token)
    messages.value = []
    const s = sessions.value.find(s => s.session_id === sessionId.value)
    if (s) s.title = '新对话'
  } catch (e) { alert('清空失败：' + e.message) }
}

onMounted(async () => {
  await loadSessionList()
  const hasSaved = loadSession()
  if (hasSaved && !props.isGuest) {
    const exists = sessions.value.some(s => s.session_id === sessionId.value)
    if (exists) await switchSession(sessionId.value)
    else createNewSession()
  } else if (!props.isGuest && sessions.value.length > 0) {
    await switchSession(sessions.value[0].session_id)
  } else {
    createNewSession()
  }
})

watch(messages, () => { scrollToBottom() }, { deep: true })
</script>

<style scoped>
/* 样式完全不变，复制你原来的即可 */
.chat-app { display: flex; height: 100vh; width: 100vw; background: #f5f7fa; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; overflow: hidden; }
.sidebar { width: 260px; background: #fff; border-right: 1px solid #e8e8e8; display: flex; flex-direction: column; transition: width 0.3s ease; flex-shrink: 0; }
.sidebar.collapsed { width: 60px; }
.sidebar-header { padding: 16px; border-bottom: 1px solid #f0f0f0; display: flex; flex-direction: column; gap: 12px; }
.logo { display: flex; align-items: center; gap: 8px; cursor: pointer; padding: 4px; border-radius: 8px; transition: background 0.2s; }
.logo:hover { background: #f5f7fa; }
.logo-icon { font-size: 24px; }
.logo-text { font-size: 18px; font-weight: 600; color: #1a1a1a; }
.new-chat-btn { display: flex; align-items: center; justify-content: center; gap: 6px; padding: 8px 12px; background: #f0f7ff; color: #409eff; border: 1px solid #d0e8ff; border-radius: 8px; cursor: pointer; font-size: 14px; font-weight: 500; transition: all 0.2s; }
.new-chat-btn:hover { background: #409eff; color: #fff; }
.session-list { flex: 1; overflow-y: auto; padding: 8px; }
.session-group-title { padding: 8px 12px; font-size: 12px; color: #999; font-weight: 500; text-transform: uppercase; letter-spacing: 0.5px; }
.session-item { display: flex; align-items: center; gap: 8px; padding: 10px 12px; border-radius: 8px; cursor: pointer; margin-bottom: 2px; font-size: 14px; color: #333; transition: all 0.2s; white-space: nowrap; overflow: hidden; }
.session-item:hover { background: #f5f7fa; }
.session-item.active { background: #e8f4ff; color: #1677ff; }
.session-icon { font-size: 16px; flex-shrink: 0; }
.session-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.empty-tip { text-align: center; color: #999; font-size: 13px; padding: 20px; }
.sidebar-footer { padding: 12px 16px; border-top: 1px solid #f0f0f0; display: flex; align-items: center; justify-content: space-between; }
.user-info { display: flex; align-items: center; gap: 8px; font-size: 14px; color: #333; }
.user-avatar { font-size: 20px; }
.logout-btn { background: transparent; border: 1px solid #e0e0e0; color: #666; padding: 4px 10px; border-radius: 6px; cursor: pointer; font-size: 12px; transition: all 0.2s; }
.logout-btn:hover { color: #ff4d4f; border-color: #ff4d4f; }
.main-content { flex: 1; display: flex; flex-direction: column; min-width: 0; background: #fff; }
.top-bar { height: 56px; background: #fff; border-bottom: 1px solid #f0f0f0; display: flex; align-items: center; padding: 0 16px; gap: 12px; flex-shrink: 0; }
.toggle-sidebar { width: 32px; height: 32px; border: 1px solid #e0e0e0; background: #fff; border-radius: 6px; cursor: pointer; font-size: 14px; color: #666; display: flex; align-items: center; justify-content: center; }
.toggle-sidebar:hover { background: #f5f7fa; }
.top-title { flex: 1; font-size: 15px; font-weight: 500; color: #1a1a1a; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.action-btn { width: 32px; height: 32px; border: 1px solid #e0e0e0; background: #fff; border-radius: 6px; cursor: pointer; font-size: 14px; display: flex; align-items: center; justify-content: center; }
.action-btn:hover { background: #f5f7fa; }
.messages-area { flex: 1; overflow-y: auto; padding: 20px 0; background: #fff; }
.welcome-screen { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; padding: 40px; text-align: center; }
.welcome-icon { font-size: 64px; margin-bottom: 20px; }
.welcome-screen h1 { font-size: 28px; font-weight: 600; color: #1a1a1a; margin: 0 0 8px 0; }
.welcome-screen p { font-size: 15px; color: #666; margin: 0 0 32px 0; }
.quick-actions { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; max-width: 480px; width: 100%; }
.quick-btn { padding: 12px 16px; background: #f5f7fa; border: 1px solid #e8e8e8; border-radius: 12px; cursor: pointer; font-size: 14px; color: #333; text-align: left; transition: all 0.2s; }
.quick-btn:hover { background: #e8f4ff; border-color: #409eff; color: #1677ff; }
.message-row { display: flex; gap: 12px; padding: 16px 24px; max-width: 900px; margin: 0 auto; width: 100%; }
.message-row.user { flex-direction: row-reverse; }
.message-avatar { width: 36px; height: 36px; border-radius: 50%; background: #f0f0f0; display: flex; align-items: center; justify-content: center; font-size: 18px; flex-shrink: 0; }
.message-row.user .message-avatar { background: #e8f4ff; }
.message-row.assistant .message-avatar { background: #f0f0f0; }
.message-body { flex: 1; min-width: 0; }
.message-header { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.message-role { font-size: 13px; font-weight: 600; color: #1a1a1a; }
.message-time { font-size: 12px; color: #999; }
.message-content { font-size: 15px; line-height: 1.7; color: #333; word-wrap: break-word; }
.input-area { padding: 16px 24px 24px; background: #fff; border-top: 1px solid #f0f0f0; flex-shrink: 0; }
.input-wrapper { display: flex; align-items: flex-end; gap: 8px; max-width: 900px; margin: 0 auto; background: #f5f7fa; border: 1px solid #e8e8e8; border-radius: 16px; padding: 8px 8px 8px 16px; transition: border-color 0.2s; }
.input-wrapper:focus-within { border-color: #409eff; background: #fff; }
.input-wrapper textarea { flex: 1; border: none; background: transparent; outline: none; resize: none; font-size: 15px; line-height: 1.5; color: #1a1a1a; max-height: 120px; min-height: 24px; padding: 4px 0; font-family: inherit; }
.input-wrapper textarea::placeholder { color: #999; }
.send-btn { width: 36px; height: 36px; border: none; background: #409eff; color: #fff; border-radius: 10px; cursor: pointer; font-size: 16px; display: flex; align-items: center; justify-content: center; transition: all 0.2s; flex-shrink: 0; }
.send-btn:hover:not(:disabled) { background: #66b1ff; }
.send-btn:disabled { background: #c0c4cc; cursor: not-allowed; }
.input-hint { display: flex; justify-content: space-between; max-width: 900px; margin: 8px auto 0; font-size: 12px; color: #999; }
.stop-hint { color: #ff4d4f; cursor: pointer; }
.stop-hint:hover { text-decoration: underline; }
.typing-indicator { display: flex; gap: 6px; padding: 8px 0; }
.typing-indicator span { width: 8px; height: 8px; background: #c0c4cc; border-radius: 50%; animation: typing 1.4s infinite ease-in-out both; }
.typing-indicator span:nth-child(1) { animation-delay: -0.32s; }
.typing-indicator span:nth-child(2) { animation-delay: -0.16s; }
@keyframes typing { 0%, 80%, 100% { transform: scale(0.6); opacity: 0.5; } 40% { transform: scale(1); opacity: 1; } }
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #d0d0d0; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #b0b0b0; }
</style>