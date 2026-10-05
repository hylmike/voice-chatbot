import { useState, useEffect, useRef, useCallback } from 'react'
import { Sidebar } from './components/Sidebar'
import { ChatCanvas } from './components/ChatCanvas'
import { InputConsole } from './components/InputConsole'
import { useChatStore } from './hooks/useChatStore'
import { audioManager } from './services/audio'
import { sendChatMessage, checkBackendHealth, createVoiceWebSocket } from './services/api'
import type { VoiceEvent } from './types'

export function App() {
  const {
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
  } = useChatStore()

  const [isBackendConnected, setIsBackendConnected] = useState(true)
  const [isVoiceMode, setIsVoiceMode] = useState(false)
  const [isRecording, setIsRecording] = useState(false)
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [isStreaming, setIsStreaming] = useState(false)
  const [volumeLevel, setVolumeLevel] = useState(0)
  const [interimTranscript, setInterimTranscript] = useState('')

  const wsRef = useRef<WebSocket | null>(null)
  const animFrameRef = useRef<number | null>(null)

  // Periodic health check
  useEffect(() => {
    let isMounted = true
    const check = async () => {
      const ok = await checkBackendHealth()
      if (isMounted) setIsBackendConnected(ok)
    }
    check()
    const interval = setInterval(check, 10000)
    return () => {
      isMounted = false
      clearInterval(interval)
    }
  }, [])

  // Animation frame loop for audio volume and speaking state
  useEffect(() => {
    const loop = () => {
      if (isVoiceMode) {
        setVolumeLevel(audioManager.getVolumeLevel())
        setIsSpeaking(audioManager.getIsPlaying())
      }
      animFrameRef.current = requestAnimationFrame(loop)
    }
    animFrameRef.current = requestAnimationFrame(loop)
    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current)
    }
  }, [isVoiceMode])

  // Handle incoming Voice WebSocket Events
  const handleVoiceEvent = useCallback(
    (event: VoiceEvent) => {
      switch (event.type) {
        case 'stt_chunk':
          setInterimTranscript(event.transcript)
          break

        case 'stt_output':
          setInterimTranscript('')
          if (event.transcript.trim()) {
            addMessage({
              role: 'user',
              content: event.transcript,
              isVoice: true,
              status: 'done',
            })
            addMessage({
              role: 'assistant',
              content: '',
              isVoice: true,
              status: 'streaming',
            })
            setIsStreaming(true)
          }
          break

        case 'agent_chunk':
          setIsStreaming(true)
          appendToLastAssistantMessage(event.text)
          break

        case 'tool_call':
          addToolCallToLastAssistant({
            id: event.toolId,
            name: event.name,
            args: event.args,
          })
          break

        case 'tool_result':
          updateToolResultInLastAssistant(event.toolCallId, event.result)
          break

        case 'tts_chunk':
          audioManager.playTTSChunk(event.audio)
          break

        case 'agent_end':
          setIsStreaming(false)
          finishAssistantMessage()
          break
      }
    },
    [
      addMessage,
      appendToLastAssistantMessage,
      addToolCallToLastAssistant,
      updateToolResultInLastAssistant,
      finishAssistantMessage,
    ]
  )

  // Stop voice mode cleanup
  const stopVoiceMode = useCallback(() => {
    setIsVoiceMode(false)
    setIsRecording(false)
    setIsSpeaking(false)
    setInterimTranscript('')
    setIsStreaming(false)
    audioManager.stopRecording()
    audioManager.stopPlayback()

    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
  }, [])

  // Start voice mode
  const startVoiceMode = useCallback(async () => {
    try {
      setIsVoiceMode(true)

      // Connect WebSocket
      const ws = createVoiceWebSocket({
        onEvent: (event) => handleVoiceEvent(event),
        onOpen: () => {
          console.log('[WS] Connected to voice backend')
        },
        onClose: () => {
          console.log('[WS] Voice connection closed')
          stopVoiceMode()
        },
        onError: (err) => {
          console.error('[WS] Connection error:', err)
        },
      })
      wsRef.current = ws

      // Start recording and sending chunks
      await audioManager.startRecording((pcm16Buffer) => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(pcm16Buffer)
        }
      })
      setIsRecording(true)
    } catch (err) {
      console.error('[Voice] Failed to start voice mode:', err)
      alert('Could not access microphone. Please check microphone permissions.')
      stopVoiceMode()
    }
  }, [handleVoiceEvent, stopVoiceMode])

  const toggleVoiceMode = () => {
    if (isVoiceMode) {
      stopVoiceMode()
    } else {
      startVoiceMode()
    }
  }

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      stopVoiceMode()
    }
  }, [stopVoiceMode])

  // Handle Text Message Send (/chat REST endpoint)
  const handleSendMessage = async (text: string) => {
    if (!text.trim()) return

    // Add user message
    addMessage({
      role: 'user',
      content: text,
      isVoice: false,
      status: 'done',
    })

    // Add placeholder assistant message
    addMessage({
      role: 'assistant',
      content: '',
      status: 'streaming',
    })
    setIsStreaming(true)

    try {
      const res = await sendChatMessage(text, activeThreadId)
      appendToLastAssistantMessage(res.response)
      finishAssistantMessage()
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err)
      appendToLastAssistantMessage(`⚠️ Error communicating with agent: ${errMsg}`)
      finishAssistantMessage()
    } finally {
      setIsStreaming(false)
    }
  }

  const handleStopPlayback = () => {
    audioManager.stopPlayback()
    setIsSpeaking(false)
  }

  return (
    <div className="flex h-screen w-screen bg-[#0d0f14] overflow-hidden select-none font-sans text-white">
      {/* Left Sidebar */}
      <Sidebar
        threads={threads}
        activeThreadId={activeThreadId}
        onSelectThread={selectThread}
        onCreateThread={createThread}
        onDeleteThread={deleteThread}
        onRenameThread={renameThread}
        isBackendConnected={isBackendConnected}
        isVoiceActive={isVoiceMode}
      />

      {/* Main Chat Canvas & Input */}
      <main className="flex-1 flex flex-col h-full min-w-0">
        <ChatCanvas
          thread={activeThread}
          onClearThread={clearCurrentThread}
          isStreaming={isStreaming}
          interimTranscript={interimTranscript}
          isVoiceActive={isVoiceMode}
        />

        <InputConsole
          onSendMessage={handleSendMessage}
          isVoiceMode={isVoiceMode}
          onToggleVoiceMode={toggleVoiceMode}
          isRecording={isRecording}
          isSpeaking={isSpeaking}
          volumeLevel={volumeLevel}
          onStopPlayback={handleStopPlayback}
          disabled={isStreaming && !isVoiceMode}
        />
      </main>
    </div>
  )
}

export default App
