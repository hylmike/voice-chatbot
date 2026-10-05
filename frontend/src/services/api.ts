import type { VoiceEvent } from '../types'

const BACKEND_HTTP_URL = import.meta.env.VITE_BACKEND_HTTP_URL || (window.location.port === '3000' ? 'http://localhost:3100' : '')
const BACKEND_WS_URL =
  import.meta.env.VITE_BACKEND_WS_URL ||
  (window.location.protocol === 'https:' ? 'wss://' : 'ws://') +
    (window.location.port === '3000' ? 'localhost:3100' : window.location.host) +
    '/ws'

export interface ChatResponse {
  response: string
  thread_id: string
}

export async function sendChatMessage(user_message: string, thread_id: string): Promise<ChatResponse> {
  const url = `${BACKEND_HTTP_URL}/chat`
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ user_message, thread_id }),
  })

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Chat API error (${res.status}): ${errorText}`)
  }

  return (await res.json()) as ChatResponse
}

export async function checkBackendHealth(): Promise<boolean> {
  try {
    const url = `${BACKEND_HTTP_URL}/health`
    const res = await fetch(url)
    return res.ok
  } catch {
    return false
  }
}

export function createVoiceWebSocket(options: {
  onEvent: (event: VoiceEvent) => void
  onOpen?: () => void
  onClose?: (e: CloseEvent) => void
  onError?: (e: Event) => void
}): WebSocket {
  const ws = new WebSocket(BACKEND_WS_URL)
  ws.binaryType = 'arraybuffer'

  ws.onopen = () => {
    options.onOpen?.()
  }

  ws.onmessage = (event) => {
    if (typeof event.data === 'string') {
      try {
        const parsed = JSON.parse(event.data) as VoiceEvent
        options.onEvent(parsed)
      } catch (err) {
        console.warn('[WS] Failed to parse JSON event:', event.data, err)
      }
    }
  }

  ws.onerror = (e) => {
    options.onError?.(e)
  }

  ws.onclose = (e) => {
    options.onClose?.(e)
  }

  return ws
}
