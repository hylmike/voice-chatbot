import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { InputConsole } from './InputConsole'

describe('InputConsole', () => {
  it('renders text mode by default and handles sending message', () => {
    const onSendMessage = vi.fn()
    const onToggleVoiceMode = vi.fn()

    render(
      <InputConsole
        onSendMessage={onSendMessage}
        isVoiceMode={false}
        onToggleVoiceMode={onToggleVoiceMode}
        isRecording={false}
        isSpeaking={false}
        volumeLevel={0}
        onStopPlayback={vi.fn()}
      />
    )

    const textarea = screen.getByPlaceholderText(/Ask anything/i)
    fireEvent.change(textarea, { target: { value: 'Hello Lingxi' } })

    const sendBtn = screen.getByTitle('Send Message')
    fireEvent.click(sendBtn)

    expect(onSendMessage).toHaveBeenCalledWith('Hello Lingxi')
  })

  it('triggers send on Enter key but not on Shift+Enter', () => {
    const onSendMessage = vi.fn()

    render(
      <InputConsole
        onSendMessage={onSendMessage}
        isVoiceMode={false}
        onToggleVoiceMode={vi.fn()}
        isRecording={false}
        isSpeaking={false}
        volumeLevel={0}
        onStopPlayback={vi.fn()}
      />
    )

    const textarea = screen.getByPlaceholderText(/Ask anything/i)
    fireEvent.change(textarea, { target: { value: 'Message 1' } })

    // Shift + Enter should NOT send
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: true })
    expect(onSendMessage).not.toHaveBeenCalled()

    // Enter without Shift should send
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false })
    expect(onSendMessage).toHaveBeenCalledWith('Message 1')
  })

  it('toggles to voice mode when mic button clicked', () => {
    const onToggleVoiceMode = vi.fn()

    render(
      <InputConsole
        onSendMessage={vi.fn()}
        isVoiceMode={false}
        onToggleVoiceMode={onToggleVoiceMode}
        isRecording={false}
        isSpeaking={false}
        volumeLevel={0}
        onStopPlayback={vi.fn()}
      />
    )

    const micBtn = screen.getByTitle('Switch to Voice Mode')
    fireEvent.click(micBtn)
    expect(onToggleVoiceMode).toHaveBeenCalledTimes(1)
  })

  it('renders voice mode console and handles interrupt', () => {
    const onStopPlayback = vi.fn()
    const onToggleVoiceMode = vi.fn()

    render(
      <InputConsole
        onSendMessage={vi.fn()}
        isVoiceMode={true}
        onToggleVoiceMode={onToggleVoiceMode}
        isRecording={true}
        isSpeaking={true}
        volumeLevel={0.5}
        onStopPlayback={onStopPlayback}
      />
    )

    expect(screen.getByText('Agent Speaking...')).toBeDefined()
    expect(screen.getByText('Live Duplex')).toBeDefined()

    const interruptBtn = screen.getByTitle('Interrupt agent speaking')
    fireEvent.click(interruptBtn)
    expect(onStopPlayback).toHaveBeenCalledTimes(1)

    const textModeBtn = screen.getByTitle('Switch back to text input')
    fireEvent.click(textModeBtn)
    expect(onToggleVoiceMode).toHaveBeenCalledTimes(1)
  })
})
