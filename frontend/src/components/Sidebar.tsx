import { useState, useMemo } from 'react'
import {
  MessageSquare,
  Plus,
  Trash2,
  Edit2,
  Check,
  X,
  Radio,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react'
import type { Thread } from '../types'

interface SidebarProps {
  threads: Thread[]
  activeThreadId: string
  onSelectThread: (id: string) => void
  onCreateThread: () => void
  onDeleteThread: (id: string) => void
  onRenameThread: (id: string, newTitle: string) => void
  isBackendConnected: boolean
  isVoiceActive: boolean
}

export function Sidebar({
  threads,
  activeThreadId,
  onSelectThread,
  onCreateThread,
  onDeleteThread,
  onRenameThread,
  isBackendConnected,
  isVoiceActive,
}: SidebarProps) {
  const [isCollapsed, setIsCollapsed] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editTitle, setEditTitle] = useState('')

  const startEditing = (thread: Thread, e: React.MouseEvent) => {
    e.stopPropagation()
    setEditingId(thread.id)
    setEditTitle(thread.title)
  }

  const saveEditing = (id: string, e?: React.MouseEvent | React.FormEvent) => {
    if (e) e.stopPropagation()
    onRenameThread(id, editTitle)
    setEditingId(null)
  }

  const cancelEditing = (e: React.MouseEvent) => {
    e.stopPropagation()
    setEditingId(null)
  }

  // Categorize threads by date
  const categorizedThreads = useMemo(() => {
    const now = Date.now()
    const oneDay = 24 * 60 * 60 * 1000
    return {
      today: threads.filter((t) => now - t.updatedAt < oneDay),
      yesterday: threads.filter((t) => now - t.updatedAt >= oneDay && now - t.updatedAt < 2 * oneDay),
      earlier: threads.filter((t) => now - t.updatedAt >= 2 * oneDay),
    }
  }, [threads])

  const renderThreadItem = (thread: Thread) => {
    const isActive = thread.id === activeThreadId
    const isEditing = editingId === thread.id

    return (
      <div
        key={thread.id}
        onClick={() => onSelectThread(thread.id)}
        className={`group relative flex items-center justify-between px-3 py-2.5 rounded-xl cursor-pointer transition-all duration-200 text-sm mb-1 ${
          isActive
            ? 'bg-gradient-to-r from-indigo-900/60 to-purple-900/40 text-white font-medium border border-indigo-700/50 shadow-sm'
            : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/60'
        }`}
      >
        <div className="flex items-center gap-2.5 min-w-0 flex-1 mr-2">
          <MessageSquare className={`w-4 h-4 shrink-0 ${isActive ? 'text-indigo-400' : 'text-zinc-500'}`} />
          {isEditing ? (
            <input
              type="text"
              value={editTitle}
              onChange={(e) => setEditTitle(e.target.value)}
              onClick={(e) => e.stopPropagation()}
              onKeyDown={(e) => {
                if (e.key === 'Enter') saveEditing(thread.id, e)
                if (e.key === 'Escape') setEditingId(null)
              }}
              autoFocus
              className="bg-zinc-900 text-white px-2 py-0.5 rounded text-xs w-full border border-indigo-500 outline-none"
            />
          ) : (
            <span className="truncate">{thread.title}</span>
          )}
        </div>

        {/* Action icons */}
        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          {isEditing ? (
            <>
              <button
                onClick={(e) => saveEditing(thread.id, e)}
                className="p-1 hover:text-emerald-400 text-zinc-400 rounded"
                title="Save"
              >
                <Check className="w-3.5 h-3.5" />
              </button>
              <button
                onClick={cancelEditing}
                className="p-1 hover:text-red-400 text-zinc-400 rounded"
                title="Cancel"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </>
          ) : (
            <>
              <button
                onClick={(e) => startEditing(thread, e)}
                className="p-1 hover:text-zinc-200 text-zinc-500 hover:bg-zinc-700/50 rounded"
                title="Rename"
              >
                <Edit2 className="w-3.5 h-3.5" />
              </button>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  onDeleteThread(thread.id)
                }}
                className="p-1 hover:text-rose-400 text-zinc-500 hover:bg-zinc-700/50 rounded"
                title="Delete"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </>
          )}
        </div>
      </div>
    )
  }

  return (
    <aside
      className={`relative flex flex-col h-full bg-[#12141a] border-r border-zinc-800/80 transition-all duration-300 z-20 ${
        isCollapsed ? 'w-16' : 'w-72'
      }`}
    >
      {/* Top Header / App Brand */}
      <div className="flex items-center justify-between p-4 border-b border-zinc-800/60">
        {!isCollapsed && (
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-tr from-indigo-600 via-purple-600 to-pink-500 flex items-center justify-center shadow-lg shadow-indigo-500/20">
              <Radio className="w-4 h-4 text-white animate-pulse" />
            </div>
            <div>
              <h1 className="text-base font-semibold text-white tracking-tight leading-none">EchoVoice AI</h1>
              <p className="text-[11px] text-zinc-400 mt-0.5">Gemini + Voice Agent</p>
            </div>
          </div>
        )}

        <button
          onClick={() => setIsCollapsed(!isCollapsed)}
          className="p-1.5 rounded-lg text-zinc-400 hover:text-white hover:bg-zinc-800 transition-colors mx-auto"
          title={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {isCollapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
        </button>
      </div>

      {/* New Chat Button */}
      <div className="p-3">
        <button
          onClick={onCreateThread}
          className={`flex items-center justify-center gap-2 w-full py-2.5 px-3 rounded-xl bg-indigo-600 hover:bg-indigo-500 active:bg-indigo-700 text-white font-medium text-sm transition-all shadow-md shadow-indigo-600/20 ${
            isCollapsed ? 'px-0' : ''
          }`}
          title="New Chat"
        >
          <Plus className="w-4 h-4 shrink-0" />
          {!isCollapsed && <span>New Chat</span>}
        </button>
      </div>

      {/* Threads List */}
      {!isCollapsed ? (
        <div className="flex-1 overflow-y-auto px-3 py-2 space-y-4">
          {categorizedThreads.today.length > 0 && (
            <div>
              <p className="text-[11px] font-semibold tracking-wider text-zinc-500 uppercase px-2 mb-1.5">Today</p>
              {categorizedThreads.today.map(renderThreadItem)}
            </div>
          )}

          {categorizedThreads.yesterday.length > 0 && (
            <div>
              <p className="text-[11px] font-semibold tracking-wider text-zinc-500 uppercase px-2 mb-1.5">Yesterday</p>
              {categorizedThreads.yesterday.map(renderThreadItem)}
            </div>
          )}

          {categorizedThreads.earlier.length > 0 && (
            <div>
              <p className="text-[11px] font-semibold tracking-wider text-zinc-500 uppercase px-2 mb-1.5">Earlier</p>
              {categorizedThreads.earlier.map(renderThreadItem)}
            </div>
          )}

          {threads.length === 0 && (
            <div className="text-center text-xs text-zinc-500 py-6">No chat history yet</div>
          )}
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto py-2 flex flex-col items-center space-y-2">
          {threads.map((t) => (
            <button
              key={t.id}
              onClick={() => onSelectThread(t.id)}
              className={`p-2.5 rounded-xl transition-colors ${
                t.id === activeThreadId
                  ? 'bg-indigo-600/30 text-indigo-400 border border-indigo-500/40'
                  : 'text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800'
              }`}
              title={t.title}
            >
              <MessageSquare className="w-4 h-4" />
            </button>
          ))}
        </div>
      )}

      {/* Bottom Status Panel */}
      <div className="p-3 border-t border-zinc-800/80 bg-[#0f1116]">
        {!isCollapsed ? (
          <div className="flex items-center justify-between text-xs text-zinc-400">
            <div className="flex items-center gap-2">
              <span
                className={`w-2 h-2 rounded-full ${
                  isBackendConnected ? 'bg-emerald-500 shadow-sm shadow-emerald-500/50' : 'bg-rose-500'
                }`}
              />
              <span>{isBackendConnected ? 'Backend Connected' : 'Disconnected'}</span>
            </div>

            {isVoiceActive && (
              <span className="flex items-center gap-1 text-[11px] text-indigo-400 font-medium bg-indigo-950/70 border border-indigo-700/50 px-2 py-0.5 rounded-full">
                <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-ping" />
                Live WS
              </span>
            )}
          </div>
        ) : (
          <div className="flex justify-center">
            <span
              className={`w-2.5 h-2.5 rounded-full ${
                isBackendConnected ? 'bg-emerald-500 shadow-sm shadow-emerald-500/50' : 'bg-rose-500'
              }`}
              title={isBackendConnected ? 'Connected' : 'Disconnected'}
            />
          </div>
        )}
      </div>
    </aside>
  )
}
