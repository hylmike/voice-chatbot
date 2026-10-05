import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { checkBackendHealth, sendChatMessage, createVoiceWebSocket } from './api'

describe('api service', () => {
  const originalFetch = globalThis.fetch

  beforeEach(() => {
    vi.restoreAllMocks()
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
  })

  describe('checkBackendHealth', () => {
    it('returns true when health endpoint responds with ok', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
      } as Response)

      const result = await checkBackendHealth()
      expect(result).toBe(true)
      expect(globalThis.fetch).toHaveBeenCalledWith(expect.stringContaining('/health'))
    })

    it('returns false when health endpoint returns non-ok or throws', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
      } as Response)

      const result = await checkBackendHealth()
      expect(result).toBe(false)

      globalThis.fetch = vi.fn().mockRejectedValue(new Error('Network error'))
      const failResult = await checkBackendHealth()
      expect(failResult).toBe(false)
    })
  })

  describe('sendChatMessage', () => {
    it('sends POST request and returns ChatResponse', async () => {
      const mockResponse = { response: 'Hello user', thread_id: 't-1' }
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => mockResponse,
      } as Response)

      const res = await sendChatMessage('Hi', 't-1')
      expect(res).toEqual(mockResponse)
      expect(globalThis.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/chat'),
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ user_message: 'Hi', thread_id: 't-1' }),
        })
      )
    })

    it('throws error when response is not ok', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        text: async () => 'Internal Error',
      } as Response)

      await expect(sendChatMessage('Hi', 't-1')).rejects.toThrow(
        'Chat API error (500): Internal Error'
      )
    })
  })

  describe('createVoiceWebSocket', () => {
    it('initializes WebSocket and registers event handlers', () => {
      const mockInstances: any[] = []
      class MockWebSocket {
        url: string
        binaryType = ''
        onopen: ((ev: Event) => void) | null = null
        onmessage: ((e: { data: any }) => void) | null = null
        onerror: ((e: any) => void) | null = null
        onclose: ((e: any) => void) | null = null
        constructor(url: string) {
          this.url = url
          mockInstances.push(this)
        }
      }

      const origWS = globalThis.WebSocket
      globalThis.WebSocket = MockWebSocket as any

      const onEvent = vi.fn()
      const onOpen = vi.fn()
      const onClose = vi.fn()
      const onError = vi.fn()

      const ws = createVoiceWebSocket({ onEvent, onOpen, onClose, onError })

      expect(ws.binaryType).toBe('arraybuffer')
      expect(ws.url).toContain('/ws')

      // Trigger events
      ws.onopen?.(new Event('open'))
      expect(onOpen).toHaveBeenCalledTimes(1)

      ws.onmessage?.({ data: JSON.stringify({ type: 'speech_started', ts: 100 }) } as any)
      expect(onEvent).toHaveBeenCalledWith({ type: 'speech_started', ts: 100 })

      // Invalid JSON is safely ignored
      ws.onmessage?.({ data: 'not-json' } as any)

      ws.onerror?.(new Event('error'))
      expect(onError).toHaveBeenCalledTimes(1)

      ws.onclose?.(new CloseEvent('close'))
      expect(onClose).toHaveBeenCalledTimes(1)

      globalThis.WebSocket = origWS
    })
  })
})
