export interface ToolCallItem {
  id: string
  name: string
  args: Record<string, unknown>
  result?: string
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: number
  isVoice?: boolean
  toolCalls?: ToolCallItem[]
  status?: 'sending' | 'streaming' | 'done' | 'error'
}

export interface Thread {
  id: string
  title: string
  createdAt: number
  updatedAt: number
  messages: Message[]
}

export type VoiceEvent =
  | { type: 'user_input'; ts: number }
  | { type: 'stt_chunk'; transcript: string; ts: number }
  | { type: 'stt_output'; transcript: string; ts: number }
  | { type: 'agent_chunk'; text: string; ts: number }
  | { type: 'agent_end'; ts: number }
  | { type: 'tool_call'; toolId: string; name: string; args: Record<string, unknown>; ts: number }
  | { type: 'tool_result'; toolCallId: string; name: string; result: string; ts: number }
  | { type: 'tts_chunk'; audio: string; ts: number }
