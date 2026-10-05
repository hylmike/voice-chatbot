import { describe, it, expect, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useChatStore } from './useChatStore'

describe('useChatStore', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('initializes with a default thread and messages', () => {
    const { result } = renderHook(() => useChatStore())
    expect(result.current.threads.length).toBeGreaterThanOrEqual(1)
    expect(result.current.activeThread).toBeDefined()
    expect(result.current.activeThreadId).toBe(result.current.activeThread?.id)
  })

  it('can create and switch to a new thread', () => {
    const { result } = renderHook(() => useChatStore())
    let newThreadId = ''
    act(() => {
      newThreadId = result.current.createThread()
    })
    expect(result.current.activeThreadId).toBe(newThreadId)
    expect(result.current.activeThread?.title).toBe('New Chat')
    expect(result.current.activeThread?.messages.length).toBe(1) // Welcome message
  })

  it('can rename and select threads', () => {
    const { result } = renderHook(() => useChatStore())
    let id = ''
    act(() => {
      id = result.current.createThread()
    })
    act(() => {
      result.current.renameThread(id, 'My Custom Thread')
    })
    const thread = result.current.threads.find((t) => t.id === id)
    expect(thread?.title).toBe('My Custom Thread')

    act(() => {
      result.current.selectThread(id)
    })
    expect(result.current.activeThreadId).toBe(id)
  })

  it('can add user message and auto-update thread title on first user query', () => {
    const { result } = renderHook(() => useChatStore())
    act(() => {
      result.current.createThread()
    })
    act(() => {
      result.current.addMessage({
        role: 'user',
        content: 'Tell me about quantum computing',
      })
    })

    expect(result.current.activeThread?.title).toBe('Tell me about quantum computing')
    expect(result.current.activeThread?.messages.length).toBe(2)
  })

  it('can stream chunks into last assistant message', () => {
    const { result } = renderHook(() => useChatStore())
    act(() => {
      result.current.createThread()
    })
    act(() => {
      result.current.addMessage({
        role: 'assistant',
        content: '',
        status: 'streaming',
      })
    })
    act(() => {
      result.current.appendToLastAssistantMessage('Hello ')
    })
    act(() => {
      result.current.appendToLastAssistantMessage('world!')
    })

    const msgs = result.current.activeThread?.messages ?? []
    const lastMsg = msgs[msgs.length - 1]
    expect(lastMsg.content).toBe('Hello world!')
    expect(lastMsg.status).toBe('streaming')

    act(() => {
      result.current.finishAssistantMessage()
    })
    const updated = result.current.activeThread?.messages ?? []
    expect(updated[updated.length - 1].status).toBe('done')
  })

  it('can add tool calls and update tool results', () => {
    const { result } = renderHook(() => useChatStore())
    act(() => {
      result.current.createThread()
    })
    act(() => {
      result.current.addMessage({
        role: 'assistant',
        content: 'Searching...',
        status: 'streaming',
      })
    })
    act(() => {
      result.current.addToolCallToLastAssistant({
        id: 'tool_1',
        name: 'tavily_search',
        args: { query: 'Paris weather' },
      })
    })

    let lastMsg = result.current.activeThread?.messages.slice(-1)[0]
    expect(lastMsg?.toolCalls?.length).toBe(1)
    expect(lastMsg?.toolCalls?.[0].name).toBe('tavily_search')
    expect(lastMsg?.toolCalls?.[0].result).toBeUndefined()

    act(() => {
      result.current.updateToolResultInLastAssistant('tool_1', '24C Sunny')
    })

    lastMsg = result.current.activeThread?.messages.slice(-1)[0]
    expect(lastMsg?.toolCalls?.[0].result).toBe('24C Sunny')
  })

  it('can clear current thread messages', () => {
    const { result } = renderHook(() => useChatStore())
    act(() => {
      result.current.createThread()
    })
    act(() => {
      result.current.addMessage({ role: 'user', content: 'test message' })
    })
    act(() => {
      result.current.clearCurrentThread()
    })

    expect(result.current.activeThread?.messages.length).toBe(0)
  })

  it('can delete thread, switching to remaining thread', () => {
    const { result } = renderHook(() => useChatStore())
    let id1 = ''
    let id2 = ''
    act(() => {
      id1 = result.current.createThread()
    })
    act(() => {
      id2 = result.current.createThread()
    })
    expect(result.current.activeThreadId).toBe(id2)

    act(() => {
      result.current.deleteThread(id2)
    })
    expect(result.current.threads.some((t) => t.id === id2)).toBe(false)
    expect(result.current.activeThreadId).toBe(id1)
  })
})
