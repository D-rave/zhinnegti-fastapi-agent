<template>
  <div class="chat-layout">
    <!-- 左侧会话列表 -->
    <aside class="sidebar">
      <div class="sidebar-header">
        <el-button type="primary" @click="createNewChat" :icon="Plus" class="new-chat-btn">
          新建对话
        </el-button>
      </div>

      <div class="session-list">
        <div
          v-for="session in chatStore.sessions"
          :key="session.session_id"
          :class="['session-item', { active: session.session_id === chatStore.currentSessionId }]"
          @click="selectSession(session.session_id)"
        >
          <el-icon><ChatDotRound /></el-icon>
          <span class="session-title">{{ session.title || '新对话' }}</span>
        </div>
      </div>

      <div class="sidebar-footer">
        <el-dropdown @command="handleCommand">
          <el-button :icon="User" text>
            {{ userStore.username || '用户' }}
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="profile">个人中心</el-dropdown-item>
              <el-dropdown-item command="dashboard">用量监控</el-dropdown-item>
              <el-dropdown-item divided command="logout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </aside>

    <!-- 右侧聊天区域 -->
    <main class="chat-main">
      <div class="messages-container" ref="messagesRef">
        <div v-if="!chatStore.hasMessages" class="empty-state">
          <el-icon :size="64" color="#dcdfe6"><ChatLineRound /></el-icon>
          <h2>智扫通智能客服</h2>
          <p>基于 ReAct Agent + RAG + 长期记忆</p>
        </div>

        <template v-else>
          <div
            v-for="(msg, index) in chatStore.messages"
            :key="msg.role + '-' + index + '-' + (msg.content?.length || 0)"
            :class="['message-row', msg.role]"
          >
            <div class="avatar">
              <el-avatar v-if="msg.role === 'user'" :icon="User" />
              <el-avatar v-else :icon="Service" class="ai-avatar" />
            </div>
            <div class="message-content">
              <div class="message-bubble">{{ msg.content || '(等待中...)' }}</div>
            </div>
          </div>
        </template>
      </div>

      <div class="input-area">
        <el-input
          v-model="inputMessage"
          type="textarea"
          :rows="3"
          placeholder="输入消息，按 Enter 发送..."
          @keydown.enter.prevent="sendMessage"
          :disabled="chatStore.isStreaming"
        />
        <el-button
          type="primary"
          @click="sendMessage"
          :loading="chatStore.isStreaming"
          :disabled="!inputMessage.trim()"
          class="send-btn"
        >
          <el-icon><Promotion /></el-icon>
        </el-button>
      </div>
    </main>
  </div>
</template>

<script setup>

import { ref, onMounted, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { useChatStore } from '@/stores/chat'
import { Plus, User, ChatDotRound, ChatLineRound, Service, Promotion } from '@element-plus/icons-vue'
import { marked } from 'marked'
import hljs from 'highlight.js'
import 'highlight.js/styles/github.css'

const router = useRouter()
const userStore = useUserStore()
const chatStore = useChatStore()
// 调试：监听 messages 变化
watch(() => chatStore.messages, (newVal) => {
    console.log('【Vue 监听】messages 变了，长度:', newVal.length)
    console.log('【Vue 监听】最后一条:', JSON.stringify(newVal[newVal.length - 1]))
}, { deep: true, immediate: true })

const inputMessage = ref('')
const messagesRef = ref(null)

// 初始化
onMounted(() => {
  userStore.init()
  chatStore.loadSessions()
})

// 监听消息变化，自动滚动到底部
watch(() => chatStore.messages.length, () => {
  nextTick(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight
    }
  })
})

const createNewChat = () => {
  chatStore.createNewSession()
}

const selectSession = (sessionId) => {
  chatStore.selectSession(sessionId)
}

const sendMessage = async () => {
  const content = inputMessage.value.trim()
  if (!content || chatStore.isStreaming) return
  inputMessage.value = ''
  await chatStore.sendChatMessage(content)
}

const handleCommand = (command) => {
  if (command === 'profile') {
    router.push('/profile')
  } else if (command === 'dashboard') {  // 【改】与路由保持一致
    router.push('/dashboard')
  } else if (command === 'logout') {
    userStore.logout()
    router.push('/login')
  }
}

// Markdown 渲染
const renderMarkdown = (text) => {
  if (!text) return ''
  marked.setOptions({
    highlight: (code, lang) => {
      if (lang && hljs.getLanguage(lang)) {
        return hljs.highlight(code, { language: lang }).value
      }
      return hljs.highlightAuto(code).value
    }
  })
  return marked(text)
}
</script>

<style scoped>
.chat-layout {
  display: flex;
  height: 100vh;
  width: 100vw;
}

.sidebar {
  width: 260px;
  background: #f5f5f5;
  border-right: 1px solid #e0e0e0;
  display: flex;
  flex-direction: column;
}

.sidebar-header {
  padding: 16px;
  border-bottom: 1px solid #e0e0e0;
}

.new-chat-btn {
  width: 100%;
}

.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.session-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  margin-bottom: 4px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.2s;
}

.session-item:hover {
  background: #e8e8e8;
}

.session-item.active {
  background: #e0e0e0;
}

.session-title {
  font-size: 14px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sidebar-footer {
  padding: 12px;
  border-top: 1px solid #e0e0e0;
}

.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: #fff;
}

.messages-container {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #909399;
}

.empty-state h2 {
  margin-top: 16px;
  font-size: 24px;
  color: #303133;
}

.message-row {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
  max-width: 80%;
}

.message-row.user {
  margin-left: auto;
  flex-direction: row-reverse;
}

.ai-avatar {
  background: #409eff;
}

.message-content {
  background: #f4f4f5;
  padding: 12px 16px;
  border-radius: 12px;
  line-height: 1.6;
}

.message-row.user .message-content {
  background: #409eff;
  color: white;
}

.input-area {
  display: flex;
  gap: 12px;
  padding: 16px 20px;
  border-top: 1px solid #e0e0e0;
}

.send-btn {
  align-self: flex-end;
}
</style>