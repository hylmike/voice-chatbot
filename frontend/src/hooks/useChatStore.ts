import { useEffect, useState } from 'react'
import type { Message, Thread, ToolCallItem } from '../types'

const STORAGE_THREADS_KEY = 'voice_chatbot_threads_v1'
const STORAGE_ACTIVE_KEY = 'voice_chatbot_active_thread_id'

function generateId(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID()
  }
  return 'thread_' + Math.random().toString(36).substring(2, 11) + Date.now().toString(36)
}

function createDefaultThread(): Thread {
  const id = generateId()
  return {
    id,
    title: 'New Chat',
    createdAt: Date.now(),
    updatedAt: Date.now(),
    messages: [
      {
        id: generateId(),
        role: 'assistant',
        content: "Hello! I am your AI assistant. You can chat with me using text or switch to voice mode using the microphone icon.",
        timestamp: Date.now(),
        status: 'done',
      },
    ],
  }
}

export function useChatStore() {
  const [threads, setThreads] = useState<Thread[]>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_THREADS_KEY)
      if (saved) {
        const parsed = JSON.parse(saved) as Thread[]
        if (Array.isArray(parsed) && parsed.length > 0) {
          return parsed
        }
      }
    } catch (e) {
      console.warn('Failed to load threads from localStorage:', e)
    }
    return [createDefaultThread()]
  })

  const [activeThreadId, setActiveThreadId] = useState<string>(() => {
    try {
      const savedId = localStorage.getItem(STORAGE_ACTIVE_KEY)
      if (savedId && threads.some((t) => t.id === savedId)) {
        return savedId
      }
    } catch {
      // fallback
    }
    return threads[0]?.id || ''
  })

  // Persist to localStorage
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_THREADS_KEY, JSON.stringify(threads))
    } catch (e) {
      console.warn('Failed to save threads:', e)
    }
  }, [threads])

  useEffect(() => {
    try {
      if (activeThreadId) {
        localStorage.setItem(STORAGE_ACTIVE_KEY, activeThreadId)
      }
    } catch (e) {
      console.warn('Failed to save activeThreadId:', e)
    }
  }, [activeThreadId])

  const activeThread = threads.find((t) => t.id === activeThreadId) || threads[0]

  const createThread = (): string => {
    const newThread = createDefaultThread()
    setThreads((prev) => [newThread, ...prev])
    setActiveThreadId(newThread.id)
    return newThread.id
  }

  const selectThread = (id: string) => {
    if (threads.some((t) => t.id === id)) {
      setActiveThreadId(id)
    }
  }

  const deleteThread = (id: string) => {
    setThreads((prev) => {
      const remaining = prev.filter((t) => t.id !== id)
      if (remaining.length === 0) {
        const fresh = createDefaultThread()
        setActiveThreadId(fresh.id)
        return [fresh]
      }
      if (activeThreadId === id) {
        setActiveThreadId(remaining[0].id)
      }
      return remaining
    })
  }

  const renameThread = (id: string, newTitle: string) => {
    setThreads((prev) =>
      prev.map((t) => (t.id === id ? { ...t, title: newTitle.trim() || 'Untitled Chat', updatedAt: Date.now() } : t))
    )
  }

  const clearCurrentThread = () => {
    if (!activeThreadId) return
    setThreads((prev) =>
      prev.map((t) =>
        t.id === activeThreadId
          ? {
              ...t,
              messages: [],
              updatedAt: Date.now(),
            }
          : t
      )
    )
  }

  const addMessage = (message: Omit<Message, 'id' | 'timestamp'>): string => {
    const msgId = generateId()
    const fullMessage: Message = {
      ...message,
      id: msgId,
      timestamp: Date.now(),
    }

    setThreads((prev) =>
      prev.map((t) => {
        if (t.id !== activeThreadId) return t

        let title = t.title
        // Auto-generate title from first user query if still "New Chat"
        if (t.title === 'New Chat' && message.role === 'user') {
          title = message.content.slice(0, 36).trim()
          if (message.content.length > 36) title += '...'
        }

        return {
          ...t,
          title,
          updatedAt: Date.now(),
          messages: [...t.messages, fullMessage],
        }
      })
    )

    return msgId
  }

  const appendToLastAssistantMessage = (chunk: string) => {
    setThreads((prev) =>
      prev.map((t) => {
        if (t.id !== activeThreadId) return t
        const lastIdx = t.messages.length - 1
        if (lastIdx < 0) return t

        const lastMsg = t.messages[lastIdx]
        if (lastMsg.role !== 'assistant') {
          // If last wasn't assistant, create a new streaming assistant message
          const newAssistant: Message = {
            id: generateId(),
            role: 'assistant',
            content: chunk,
            timestamp: Date.now(),
            status: 'streaming',
          }
          return {
            ...t,
            updatedAt: Date.now(),
            messages: [...t.messages, newAssistant],
          }
        }

        const updatedMessages = [...t.messages]
        updatedMessages[lastIdx] = {
          ...lastMsg,
          content: lastMsg.content + chunk,
          status: 'streaming',
        }
        return {
          ...t,
          updatedAt: Date.now(),
          messages: updatedMessages,
        }
      })
    )
  }

  const addToolCallToLastAssistant = (toolCall: { id: string; name: string; args: Record<string, unknown> }) => {
    setThreads((prev) =>
      prev.map((t) => {
        if (t.id !== activeThreadId) return t
        const lastIdx = t.messages.length - 1
        if (lastIdx < 0) return t

        const lastMsg = t.messages[lastIdx]
        if (lastMsg.role !== 'assistant') {
          const newAssistant: Message = {
            id: generateId(),
            role: 'assistant',
            content: '',
            timestamp: Date.now(),
            status: 'streaming',
            toolCalls: [{ id: toolCall.id, name: toolCall.name, args: toolCall.args }],
          }
          return {
            ...t,
            updatedAt: Date.now(),
            messages: [...t.messages, newAssistant],
          }
        }

        const toolCalls: ToolCallItem[] = [...(lastMsg.toolCalls || [])]
        if (!toolCalls.some((tc) => tc.id === toolCall.id)) {
          toolCalls.push({
            id: toolCall.id,
            name: toolCall.name,
            args: toolCall.args,
          })
        }

        const updatedMessages = [...t.messages]
        updatedMessages[lastIdx] = {
          ...lastMsg,
          toolCalls,
        }
        return {
          ...t,
          updatedAt: Date.now(),
          messages: updatedMessages,
        }
      })
    )
  }

  const updateToolResultInLastAssistant = (toolCallId: string, result: string) => {
    setThreads((prev) =>
      prev.map((t) => {
        if (t.id !== activeThreadId) return t
        const lastIdx = t.messages.length - 1
        if (lastIdx < 0) return t

        const lastMsg = t.messages[lastIdx]
        if (lastMsg.role !== 'assistant' || !lastMsg.toolCalls) return t

        const toolCalls = lastMsg.toolCalls.map((tc) => (tc.id === toolCallId ? { ...tc, result } : tc))

        const updatedMessages = [...t.messages]
        updatedMessages[lastIdx] = {
          ...lastMsg,
          toolCalls,
        }
        return {
          ...t,
          updatedAt: Date.now(),
          messages: updatedMessages,
        }
      })
    )
  }

  const finishAssistantMessage = () => {
    setThreads((prev) =>
      prev.map((t) => {
        if (t.id !== activeThreadId) return t
        const lastIdx = t.messages.length - 1
        if (lastIdx < 0) return t
        const lastMsg = t.messages[lastIdx]
        if (lastMsg.role === 'assistant') {
          const updatedMessages = [...t.messages]
          updatedMessages[lastIdx] = { ...lastMsg, status: 'done' }
          return { ...t, messages: updatedMessages }
        }
        return t
      })
    )
  }

  return {
    threads,
    activeThread,
    activeThreadId,
    createThread,
    selectThread,
    deleteThread,
    renameThread,
    clearCurrentThread,
    addMessage,
    appendToLastAssistantMessage,
    addToolCallToLastAssistant,
    updateToolResultInLastAssistant,
    finishAssistantMessage,
  }
}
