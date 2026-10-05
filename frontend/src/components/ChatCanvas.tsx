import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import {
  Sparkles,
  User,
  Mic,
  Search,
  Copy,
  Check,
  ChevronDown,
  ChevronRight,
  Trash2,
  Volume2,
} from 'lucide-react'
import type { Message, Thread } from '../types'

interface ChatCanvasProps {
  thread?: Thread
  onClearThread: () => void
  isStreaming: boolean
  interimTranscript: string
  isVoiceActive: boolean
}

export function ChatCanvas({
  thread,
  onClearThread,
  isStreaming,
  interimTranscript,
  isVoiceActive,
}: ChatCanvasProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [expandedTools, setExpandedTools] = useState<Record<string, boolean>>({})

  // Auto-scroll to bottom on new messages or streaming
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [thread?.messages, isStreaming, interimTranscript])

  const copyToClipboard = (text: string, id: string) => {
    navigator.clipboard.writeText(text)
    setCopiedId(id)
    setTimeout(() => setCopiedId(null), 2000)
  }

  const toggleToolExpand = (toolId: string) => {
    setExpandedTools((prev) => ({
      ...prev,
      [toolId]: !prev[toolId],
    }))
  }

  return (
    <div className="flex-1 flex flex-col h-full bg-[#0d0f14] overflow-hidden">
      {/* Top Header */}
      <div className="h-16 px-6 border-b border-zinc-800/80 flex items-center justify-between shrink-0 bg-[#12141a]/60 backdrop-blur-md">
        <div className="flex items-center gap-3">
          <div className="flex flex-col">
            <h2 className="text-base font-semibold text-white truncate max-w-md">
              {thread?.title || 'New Chat'}
            </h2>
            <div className="flex items-center gap-2 text-xs text-zinc-400">
              <span className="flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                Gemini 3.7 Flash Agent
              </span>
              <span>•</span>
              <span className="text-zinc-500">ID: {thread?.id?.slice(0, 8)}...</span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {isVoiceActive && (
            <span className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-indigo-950/80 border border-indigo-700/60 text-xs font-medium text-indigo-300 animate-pulse">
              <Mic className="w-3.5 h-3.5 text-indigo-400" />
              Voice Mode Active
            </span>
          )}

          {thread && thread.messages.length > 0 && (
            <button
              onClick={onClearThread}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-zinc-400 hover:text-rose-400 hover:bg-zinc-800 transition-colors"
              title="Clear Conversation"
            >
              <Trash2 className="w-3.5 h-3.5" />
              <span>Clear</span>
            </button>
          )}
        </div>
      </div>

      {/* Messages Canvas */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 md:px-8 py-6 space-y-6">
        {(!thread || thread.messages.length === 0) && !interimTranscript && (
          <div className="h-full flex flex-col items-center justify-center text-center max-w-md mx-auto my-auto py-12">
            <div className="w-14 h-14 rounded-2xl bg-gradient-to-tr from-indigo-500 to-purple-600 flex items-center justify-center mb-4 shadow-xl shadow-indigo-500/20">
              <Sparkles className="w-7 h-7 text-white" />
            </div>
            <h3 className="text-lg font-semibold text-white mb-2">How can I help you today?</h3>
            <p className="text-sm text-zinc-400 mb-6">
              Ask any question, brainstorm, or conduct real-time web research using text or voice.
            </p>
          </div>
        )}

        {thread?.messages.map((msg: Message) => {
          const isUser = msg.role === 'user'

          return (
            <div
              key={msg.id}
              className={`flex items-start gap-3.5 ${isUser ? 'justify-end' : 'justify-start'}`}
            >
              {!isUser && (
                <div className="w-8 h-8 rounded-xl bg-gradient-to-tr from-indigo-600 to-purple-600 flex items-center justify-center shrink-0 shadow-md shadow-indigo-600/20 mt-1">
                  <Sparkles className="w-4 h-4 text-white" />
                </div>
              )}

              <div
                className={`max-w-[85%] md:max-w-[75%] rounded-2xl px-4 py-3.5 text-sm leading-relaxed transition-all shadow-sm ${
                  isUser
                    ? 'bg-gradient-to-r from-indigo-600 to-indigo-700 text-white rounded-tr-sm'
                    : 'bg-[#181b22] border border-zinc-800/80 text-zinc-200 rounded-tl-sm'
                }`}
              >
                {/* Header info in bubble */}
                <div className="flex items-center justify-between gap-4 mb-1.5 text-[11px] opacity-70">
                  <span className="font-medium flex items-center gap-1">
                    {isUser ? (
                      <>
                        <User className="w-3 h-3" />
                        {msg.isVoice ? 'You (Voice)' : 'You'}
                      </>
                    ) : (
                      <>
                        <Sparkles className="w-3 h-3 text-indigo-400" />
                        EchoVoice AI
                      </>
                    )}
                  </span>
                  <span>{new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                </div>

                {/* Tool calls (e.g. Tavily search) */}
                {!isUser && msg.toolCalls && msg.toolCalls.length > 0 && (
                  <div className="my-2 space-y-2">
                    {msg.toolCalls.map((tc) => {
                      const isExpanded = !!expandedTools[tc.id]
                      const query = (tc.args as { query?: string })?.query || JSON.stringify(tc.args)

                      return (
                        <div
                          key={tc.id}
                          className="rounded-lg bg-zinc-900/80 border border-zinc-700/60 overflow-hidden text-xs"
                        >
                          <button
                            onClick={() => toggleToolExpand(tc.id)}
                            className="w-full px-3 py-2 flex items-center justify-between text-left hover:bg-zinc-800/60 transition-colors"
                          >
                            <div className="flex items-center gap-2 text-indigo-300 font-medium truncate">
                              <Search className="w-3.5 h-3.5 shrink-0 text-indigo-400" />
                              <span className="truncate">
                                Web Search: <span className="text-zinc-300 italic font-normal">"{query}"</span>
                              </span>
                            </div>
                            <div className="flex items-center gap-1.5 shrink-0 text-zinc-400">
                              <span className="text-[10px] bg-zinc-800 px-1.5 py-0.5 rounded text-emerald-400">
                                {tc.result ? 'Completed' : 'Running...'}
                              </span>
                              {isExpanded ? (
                                <ChevronDown className="w-3.5 h-3.5" />
                              ) : (
                                <ChevronRight className="w-3.5 h-3.5" />
                              )}
                            </div>
                          </button>

                          {isExpanded && tc.result && (
                            <div className="p-3 border-t border-zinc-800 bg-zinc-950/60 text-zinc-300 text-xs font-mono max-h-40 overflow-y-auto whitespace-pre-wrap">
                              {tc.result}
                            </div>
                          )}
                        </div>
                      )
                    })}
                  </div>
                )}

                {/* Message Content */}
                <div className="prose prose-invert prose-sm max-w-none break-words">
                  {isUser ? (
                    <p className="whitespace-pre-wrap m-0">{msg.content}</p>
                  ) : (
                    <ReactMarkdown>{msg.content}</ReactMarkdown>
                  )}
                </div>

                {/* Actions / Status footer */}
                {!isUser && (
                  <div className="flex items-center justify-between mt-3 pt-2 border-t border-zinc-800/50 text-xs text-zinc-400">
                    <div className="flex items-center gap-2">
                      {msg.status === 'streaming' && (
                        <span className="flex items-center gap-1 text-indigo-400 font-medium">
                          <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-pulse" />
                          Streaming...
                        </span>
                      )}
                      {msg.isVoice && (
                        <span className="flex items-center gap-1 text-zinc-400">
                          <Volume2 className="w-3 h-3 text-purple-400" />
                          Spoken Audio
                        </span>
                      )}
                    </div>

                    <button
                      onClick={() => copyToClipboard(msg.content, msg.id)}
                      className="p-1 hover:text-white rounded hover:bg-zinc-800 transition-colors"
                      title="Copy response"
                    >
                      {copiedId === msg.id ? (
                        <Check className="w-3.5 h-3.5 text-emerald-400" />
                      ) : (
                        <Copy className="w-3.5 h-3.5 text-zinc-500" />
                      )}
                    </button>
                  </div>
                )}
              </div>

              {isUser && (
                <div className="w-8 h-8 rounded-xl bg-zinc-700/80 flex items-center justify-center shrink-0 mt-1">
                  {msg.isVoice ? <Mic className="w-4 h-4 text-white" /> : <User className="w-4 h-4 text-white" />}
                </div>
              )}
            </div>
          )
        })}

        {/* Live Interim Speech Preview */}
        {interimTranscript && (
          <div className="flex items-start gap-3.5 justify-end">
            <div className="max-w-[75%] rounded-2xl rounded-tr-sm px-4 py-3 text-sm bg-indigo-950/40 border border-indigo-500/40 text-indigo-200 shadow-md">
              <div className="flex items-center gap-2 text-xs text-indigo-400 font-medium mb-1">
                <Mic className="w-3.5 h-3.5 animate-pulse text-indigo-400" />
                <span>Listening (live transcription)...</span>
              </div>
              <p className="italic text-zinc-300">{interimTranscript}</p>
            </div>
            <div className="w-8 h-8 rounded-xl bg-indigo-700 flex items-center justify-center shrink-0 mt-1 animate-pulse">
              <Mic className="w-4 h-4 text-white" />
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
