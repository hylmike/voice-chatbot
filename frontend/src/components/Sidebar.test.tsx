import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { Sidebar } from './Sidebar'
import type { Thread } from '../types'

describe('Sidebar', () => {
  const mockThreads: Thread[] = [
    {
      id: 'thread-1',
      title: 'First Chat',
      createdAt: Date.now(),
      updatedAt: Date.now(),
      messages: [],
    },
    {
      id: 'thread-2',
      title: 'Second Chat',
      createdAt: Date.now() - 3600000,
      updatedAt: Date.now() - 3600000,
      messages: [],
    },
  ]

  it('renders branding and threads list', () => {
    render(
      <Sidebar
        threads={mockThreads}
        activeThreadId="thread-1"
        onSelectThread={vi.fn()}
        onCreateThread={vi.fn()}
        onDeleteThread={vi.fn()}
        onRenameThread={vi.fn()}
        isBackendConnected={true}
        isVoiceActive={false}
      />
    )

    expect(screen.getByText('Lingxi AI')).toBeDefined()
    expect(screen.getByText('Text + Voice Agent')).toBeDefined()
    expect(screen.getByText('First Chat')).toBeDefined()
    expect(screen.getByText('Second Chat')).toBeDefined()
    expect(screen.getByText('Backend Connected')).toBeDefined()
  })

  it('calls onCreateThread when New Chat is clicked', () => {
    const onCreateThread = vi.fn()
    render(
      <Sidebar
        threads={mockThreads}
        activeThreadId="thread-1"
        onSelectThread={vi.fn()}
        onCreateThread={onCreateThread}
        onDeleteThread={vi.fn()}
        onRenameThread={vi.fn()}
        isBackendConnected={true}
        isVoiceActive={false}
      />
    )

    const newChatBtn = screen.getByTitle('New Chat')
    fireEvent.click(newChatBtn)
    expect(onCreateThread).toHaveBeenCalledTimes(1)
  })

  it('calls onSelectThread when clicking a thread', () => {
    const onSelectThread = vi.fn()
    render(
      <Sidebar
        threads={mockThreads}
        activeThreadId="thread-1"
        onSelectThread={onSelectThread}
        onCreateThread={vi.fn()}
        onDeleteThread={vi.fn()}
        onRenameThread={vi.fn()}
        isBackendConnected={true}
        isVoiceActive={false}
      />
    )

    const secondChat = screen.getByText('Second Chat')
    fireEvent.click(secondChat)
    expect(onSelectThread).toHaveBeenCalledWith('thread-2')
  })

  it('calls onDeleteThread when delete button clicked', () => {
    const onDeleteThread = vi.fn()
    render(
      <Sidebar
        threads={mockThreads}
        activeThreadId="thread-1"
        onSelectThread={vi.fn()}
        onCreateThread={vi.fn()}
        onDeleteThread={onDeleteThread}
        onRenameThread={vi.fn()}
        isBackendConnected={true}
        isVoiceActive={false}
      />
    )

    const deleteButtons = screen.getAllByTitle('Delete')
    fireEvent.click(deleteButtons[0])
    expect(onDeleteThread).toHaveBeenCalledWith('thread-1')
  })

  it('can start and save renaming a thread', () => {
    const onRenameThread = vi.fn()
    render(
      <Sidebar
        threads={mockThreads}
        activeThreadId="thread-1"
        onSelectThread={vi.fn()}
        onCreateThread={vi.fn()}
        onDeleteThread={vi.fn()}
        onRenameThread={onRenameThread}
        isBackendConnected={true}
        isVoiceActive={false}
      />
    )

    const renameButtons = screen.getAllByTitle('Rename')
    fireEvent.click(renameButtons[0])

    const input = screen.getByDisplayValue('First Chat')
    fireEvent.change(input, { target: { value: 'Renamed Chat' } })

    const saveBtn = screen.getByTitle('Save')
    fireEvent.click(saveBtn)

    expect(onRenameThread).toHaveBeenCalledWith('thread-1', 'Renamed Chat')
  })

  it('can collapse and expand sidebar', () => {
    render(
      <Sidebar
        threads={mockThreads}
        activeThreadId="thread-1"
        onSelectThread={vi.fn()}
        onCreateThread={vi.fn()}
        onDeleteThread={vi.fn()}
        onRenameThread={vi.fn()}
        isBackendConnected={true}
        isVoiceActive={true}
      />
    )

    expect(screen.getByText('Live WS')).toBeDefined()

    const collapseBtn = screen.getByTitle('Collapse sidebar')
    fireEvent.click(collapseBtn)

    // In collapsed mode
    expect(screen.getByTitle('Expand sidebar')).toBeDefined()
  })
})
