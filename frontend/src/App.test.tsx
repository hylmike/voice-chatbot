import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { App } from './App'
import * as api from './services/api'
import { audioManager } from './services/audio'

describe('App Component', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
    vi.spyOn(api, 'checkBackendHealth').mockResolvedValue(true)
  })

  it('renders application with sidebar, canvas, and input console', async () => {
    render(<App />)

    expect(screen.getAllByText('Lingxi AI').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('Text + Voice Agent')).toBeDefined()
    expect(screen.getByPlaceholderText(/Ask anything/i)).toBeDefined()
  })

  it('sends text chat message through REST endpoint', async () => {
    const mockSend = vi.spyOn(api, 'sendChatMessage').mockResolvedValue({
      response: 'This is a test agent reply.',
      thread_id: 't-123',
    })

    render(<App />)

    const textarea = screen.getByPlaceholderText(/Ask anything/i)
    fireEvent.change(textarea, { target: { value: 'What is your name?' } })

    const sendBtn = screen.getByTitle('Send Message')
    await act(async () => {
      fireEvent.click(sendBtn)
    })

    expect(mockSend).toHaveBeenCalledWith('What is your name?', expect.any(String))
    await waitFor(() => {
      expect(screen.getByText('This is a test agent reply.')).toBeDefined()
    })
  })

  it('toggles voice mode and handles voice events', async () => {
    let capturedOptions: any = null
    const mockWs = {
      readyState: 1,
      send: vi.fn(),
      close: vi.fn(),
    }

    vi.spyOn(api, 'createVoiceWebSocket').mockImplementation((options: any) => {
      capturedOptions = options
      return mockWs as any
    })

    vi.spyOn(audioManager, 'startRecording').mockResolvedValue(undefined)
    const stopPlaybackSpy = vi.spyOn(audioManager, 'stopPlayback')
    const playTTSSpy = vi.spyOn(audioManager, 'playTTSChunk').mockResolvedValue(undefined)

    render(<App />)

    // Switch to voice mode
    const micToggleBtn = screen.getByTitle('Switch to Voice Mode')
    await act(async () => {
      fireEvent.click(micToggleBtn)
    })

    expect(screen.getByText('Live Duplex')).toBeDefined()
    expect(capturedOptions).not.toBeNull()

    // 1. Receive stt_chunk (interim transcript)
    act(() => {
      capturedOptions.onEvent({
        type: 'stt_chunk',
        transcript: 'transcribing live...',
        ts: Date.now(),
      })
    })
    expect(screen.getByText('transcribing live...')).toBeDefined()

    // 2. Receive stt_output (finalized turn)
    act(() => {
      capturedOptions.onEvent({
        type: 'stt_output',
        transcript: 'What can you do?',
        ts: Date.now(),
      })
    })
    expect(screen.getAllByText('What can you do?').length).toBeGreaterThanOrEqual(1)

    // 3. Receive tts_chunk
    act(() => {
      capturedOptions.onEvent({
        type: 'tts_chunk',
        audio: 'dGVzdA==',
        ts: Date.now(),
      })
    })
    expect(playTTSSpy).toHaveBeenCalledWith('dGVzdA==')

    // 4. Receive speech_started (barge-in interrupt)
    act(() => {
      capturedOptions.onEvent({
        type: 'speech_started',
        ts: Date.now(),
      })
    })
    expect(stopPlaybackSpy).toHaveBeenCalled()

    // Switch back to text mode
    const textModeBtn = screen.getByTitle('Switch back to text input')
    act(() => {
      fireEvent.click(textModeBtn)
    })
    expect(screen.getByPlaceholderText(/Ask anything/i)).toBeDefined()
  })
})
