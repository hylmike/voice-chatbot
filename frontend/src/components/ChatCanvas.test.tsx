import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ChatCanvas } from './ChatCanvas'
import type { Thread } from '../types'

describe('ChatCanvas', () => {
  it('renders welcome empty state when thread has no messages', () => {
    const thread: Thread = {
      id: 't-1',
      title: 'Empty Thread',
      createdAt: Date.now(),
      updatedAt: Date.now(),
      messages: [],
    }

    render(
      <ChatCanvas
        thread={thread}
        onClearThread={vi.fn()}
        isStreaming={false}
        interimTranscript=""
        isVoiceActive={false}
      />
    )

    expect(screen.getByText('How can I help you today?')).toBeDefined()
    expect(screen.getByText('Gemini 3.7 Flash Agent')).toBeDefined()
  })

  it('renders user and assistant messages with voice badge and cleaned content', () => {
    const thread: Thread = {
      id: 't-1',
      title: 'Chat Thread',
      createdAt: Date.now(),
      updatedAt: Date.now(),
      messages: [
        {
          id: 'm-1',
          role: 'user',
          content: 'What is artificial intelligence?',
          timestamp: Date.now(),
          isVoice: true,
          status: 'done',
        },
        {
          id: 'm-2',
          role: 'assistant',
          content: 'AI is smart <break time="300ms"/> software.',
          timestamp: Date.now(),
          isVoice: true,
          status: 'done',
        },
      ],
    }

    render(
      <ChatCanvas
        thread={thread}
        onClearThread={vi.fn()}
        isStreaming={false}
        interimTranscript=""
        isVoiceActive={true}
      />
    )

    expect(screen.getByText('What is artificial intelligence?')).toBeDefined()
    expect(screen.getByText('You (Voice)')).toBeDefined()
    expect(screen.getByText('Spoken Audio')).toBeDefined()
    expect(screen.getByText('Voice Mode Active')).toBeDefined()

    // Assert that <break .../> was cleaned and not rendered
    expect(screen.queryByText(/<break/i)).toBeNull()
  })

  it('renders tool calls and toggles expanded results', () => {
    const thread: Thread = {
      id: 't-1',
      title: 'Tool Thread',
      createdAt: Date.now(),
      updatedAt: Date.now(),
      messages: [
        {
          id: 'm-1',
          role: 'assistant',
          content: 'Here is the info.',
          timestamp: Date.now(),
          status: 'done',
          toolCalls: [
            {
              id: 'call-1',
              name: 'tavily_search',
              args: { query: 'latest tech news' },
              result: 'Major tech announcements today...',
            },
          ],
        },
      ],
    }

    render(
      <ChatCanvas
        thread={thread}
        onClearThread={vi.fn()}
        isStreaming={false}
        interimTranscript=""
        isVoiceActive={false}
      />
    )

    expect(screen.getByText('Completed')).toBeDefined()

    // Click to expand tool call result
    const toolBtn = screen.getByRole('button', { name: /latest tech news/i })
    fireEvent.click(toolBtn)

    expect(screen.getByText(/Major tech announcements today/i)).toBeDefined()
  })

  it('renders interim transcript while user is speaking', () => {
    render(
      <ChatCanvas
        thread={undefined}
        onClearThread={vi.fn()}
        isStreaming={false}
        interimTranscript="I am asking a question"
        isVoiceActive={true}
      />
    )

    expect(screen.getByText('Listening (live transcription)...')).toBeDefined()
    expect(screen.getByText('I am asking a question')).toBeDefined()
  })

  it('calls onClearThread when clear button clicked', () => {
    const onClearThread = vi.fn()
    const thread: Thread = {
      id: 't-1',
      title: 'Active Thread',
      createdAt: Date.now(),
      updatedAt: Date.now(),
      messages: [
        {
          id: 'm-1',
          role: 'user',
          content: 'Hello',
          timestamp: Date.now(),
        },
      ],
    }

    render(
      <ChatCanvas
        thread={thread}
        onClearThread={onClearThread}
        isStreaming={false}
        interimTranscript=""
        isVoiceActive={false}
      />
    )

    const clearBtn = screen.getByTitle('Clear Conversation')
    fireEvent.click(clearBtn)
    expect(onClearThread).toHaveBeenCalledTimes(1)
  })
})
