import { useState, useRef, useEffect, type KeyboardEvent } from 'react'
import {
  Send,
  Mic,
  Square,
  Keyboard,
  Sparkles,
  Volume2,
} from 'lucide-react'

interface InputConsoleProps {
  onSendMessage: (text: string) => void
  isVoiceMode: boolean
  onToggleVoiceMode: () => void
  isRecording: boolean
  isSpeaking: boolean
  volumeLevel: number
  onStopPlayback: () => void
  disabled?: boolean
}

export function InputConsole({
  onSendMessage,
  isVoiceMode,
  onToggleVoiceMode,
  isRecording,
  isSpeaking,
  volumeLevel,
  onStopPlayback,
  disabled = false,
}: InputConsoleProps) {
  const [text, setText] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 120)}px`
    }
  }, [text])

  const handleSend = () => {
    if (!text.trim() || disabled) return
    onSendMessage(text.trim())
    setText('')
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="p-4 md:p-6 border-t border-zinc-800/80 bg-[#12141a]/90 backdrop-blur-lg">
      <div className="max-w-4xl mx-auto">
        {!isVoiceMode ? (
          /* Text Input Mode */
          <div className="relative flex items-end gap-2.5 bg-[#181b22] border border-zinc-700/70 focus-within:border-indigo-500/80 focus-within:ring-2 focus-within:ring-indigo-500/20 rounded-2xl p-2 transition-all shadow-lg">
            <textarea
              ref={textareaRef}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask anything... (Shift+Enter for newline)"
              rows={1}
              disabled={disabled}
              className="flex-1 bg-transparent border-0 text-white placeholder-zinc-500 text-sm px-3 py-2 outline-none resize-none max-h-32 min-h-[40px] leading-relaxed"
            />

            <div className="flex items-center gap-2 pb-1 pr-1">
              {/* Voice mode toggle button with pulsing glow */}
              <button
                type="button"
                onClick={onToggleVoiceMode}
                className="group relative p-2.5 rounded-xl bg-zinc-800 hover:bg-indigo-600/30 text-zinc-400 hover:text-indigo-400 transition-all border border-zinc-700/50 hover:border-indigo-500/40"
                title="Switch to Voice Mode"
              >
                <Mic className="w-4 h-4 transition-transform group-hover:scale-110" />
                <span className="sr-only">Voice Mode</span>
              </button>

              {/* Send button */}
              <button
                type="button"
                onClick={handleSend}
                disabled={!text.trim() || disabled}
                className={`p-2.5 rounded-xl flex items-center justify-center transition-all ${
                  text.trim() && !disabled
                    ? 'bg-indigo-600 hover:bg-indigo-500 text-white shadow-md shadow-indigo-600/30'
                    : 'bg-zinc-800 text-zinc-500 cursor-not-allowed'
                }`}
                title="Send Message"
              >
                <Send className="w-4 h-4" />
                <span className="sr-only">Send</span>
              </button>
            </div>
          </div>
        ) : (
          /* Real-Time Voice Mode Console */
          <div className="flex flex-col md:flex-row items-center justify-between gap-4 bg-gradient-to-r from-indigo-950/40 via-purple-950/30 to-zinc-900 border border-indigo-700/40 rounded-2xl p-4 shadow-xl">
            {/* Status indicator and waveform */}
            <div className="flex items-center gap-4 flex-1">
              {/* Circular glowing mic button */}
              <div className="relative flex items-center justify-center">
                <div
                  className={`absolute inset-0 rounded-full transition-all duration-300 ${
                    isSpeaking
                      ? 'bg-purple-500/30 animate-ping'
                      : isRecording
                      ? 'bg-indigo-500/30 animate-pulse'
                      : 'bg-transparent'
                  }`}
                  style={{ transform: `scale(${1 + volumeLevel * 1.5})` }}
                />
                <div
                  className={`relative w-12 h-12 rounded-full flex items-center justify-center transition-all shadow-lg ${
                    isSpeaking
                      ? 'bg-gradient-to-tr from-purple-600 to-pink-500 text-white shadow-purple-500/30'
                      : 'bg-gradient-to-tr from-indigo-600 to-purple-600 text-white shadow-indigo-500/30'
                  }`}
                >
                  {isSpeaking ? (
                    <Volume2 className="w-5 h-5 animate-bounce" />
                  ) : (
                    <Mic className="w-5 h-5" />
                  )}
                </div>
              </div>

              {/* Status details */}
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-white">
                    {isSpeaking ? 'Agent Speaking...' : isRecording ? 'Listening to your voice...' : 'Connecting...'}
                  </span>
                  <span className="text-[11px] px-2 py-0.5 rounded-full bg-indigo-900/80 text-indigo-300 border border-indigo-700/50">
                    Live Duplex
                  </span>
                </div>
                <p className="text-xs text-zinc-400 mt-0.5">
                  Speak naturally into your microphone. The agent listens and answers in real-time.
                </p>
              </div>
            </div>

            {/* Audio Wave Bars Visualizer */}
            <div className="flex items-center gap-1.5 h-8 px-4">
              {[0.4, 0.7, 0.3, 0.9, 0.6, 0.8, 0.5, 0.3, 0.7, 0.5].map((heightMultiplier, i) => {
                const dynamicHeight = Math.max(
                  6,
                  Math.min(32, (volumeLevel * 40 + 8) * heightMultiplier)
                )
                return (
                  <div
                    key={i}
                    className={`w-1 rounded-full transition-all duration-75 ${
                      isSpeaking
                        ? 'bg-purple-400'
                        : isRecording
                        ? 'bg-indigo-400'
                        : 'bg-zinc-600'
                    }`}
                    style={{ height: `${dynamicHeight}px` }}
                  />
                )
              })}
            </div>

            {/* Voice Console Controls */}
            <div className="flex items-center gap-2">
              {isSpeaking && (
                <button
                  type="button"
                  onClick={onStopPlayback}
                  className="flex items-center gap-1.5 px-3 py-2 rounded-xl bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs font-medium border border-zinc-700/60 transition-colors"
                  title="Interrupt agent speaking"
                >
                  <Square className="w-3.5 h-3.5 fill-current text-rose-400" />
                  <span>Interrupt</span>
                </button>
              )}

              <button
                type="button"
                onClick={onToggleVoiceMode}
                className="flex items-center gap-1.5 px-3 py-2 rounded-xl bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs font-medium border border-zinc-700/60 transition-colors"
                title="Switch back to text input"
              >
                <Keyboard className="w-3.5 h-3.5" />
                <span>Text Mode</span>
              </button>
            </div>
          </div>
        )}

        <div className="flex items-center justify-between text-[11px] text-zinc-500 mt-2 px-1">
          <span>Powered by Gemini 3.7 Flash, AssemblyAI STT & Cartesia TTS</span>
          <span className="flex items-center gap-1">
            <Sparkles className="w-3 h-3 text-indigo-400" />
            Web Search enabled
          </span>
        </div>
      </div>
    </div>
  )
}
