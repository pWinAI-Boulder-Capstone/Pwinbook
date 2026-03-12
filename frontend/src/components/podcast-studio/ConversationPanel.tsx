'use client'

import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'
import type { ConversationMessage, SearchResult, StudioStatus } from '@/lib/types/podcast-studio-ws'

// Color configurations for each speaker slot (0-3)
const SPEAKER_COLOR_CLASSES = [
  {
    bubble: 'bg-blue-50 dark:bg-blue-950/40 border-blue-200 dark:border-blue-800',
    badge: 'bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300',
    cursor: 'bg-blue-500',
  },
  {
    bubble: 'bg-emerald-50 dark:bg-emerald-950/40 border-emerald-200 dark:border-emerald-800',
    badge: 'bg-emerald-100 dark:bg-emerald-900 text-emerald-700 dark:text-emerald-300',
    cursor: 'bg-emerald-500',
  },
  {
    bubble: 'bg-violet-50 dark:bg-violet-950/40 border-violet-200 dark:border-violet-800',
    badge: 'bg-violet-100 dark:bg-violet-900 text-violet-700 dark:text-violet-300',
    cursor: 'bg-violet-500',
  },
  {
    bubble: 'bg-amber-50 dark:bg-amber-950/40 border-amber-200 dark:border-amber-800',
    badge: 'bg-amber-100 dark:bg-amber-900 text-amber-700 dark:text-amber-300',
    cursor: 'bg-amber-500',
  },
]

// ---------------------------------------------------------------------------
// FactCheckCard — inline search result card
// ---------------------------------------------------------------------------

function FactCheckCard({ msg }: { msg: Extract<ConversationMessage, { type: 'fact_check' }> }) {
  const [expanded, setExpanded] = useState(false)
  const hasResults = msg.status === 'done' && msg.results && msg.results.length > 0

  return (
    <div className="flex justify-center">
      <div
        className={cn(
          'text-xs rounded-xl border px-3 py-2 max-w-[85%] w-full',
          msg.status === 'searching'
            ? 'bg-yellow-50 dark:bg-yellow-950/30 border-yellow-200 dark:border-yellow-800'
            : 'bg-sky-50 dark:bg-sky-950/30 border-sky-200 dark:border-sky-800',
        )}
      >
        {/* Header row */}
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5">
            {msg.status === 'searching' ? (
              <span className="w-1.5 h-1.5 rounded-full bg-yellow-500 animate-pulse flex-shrink-0" />
            ) : (
              <span className="w-1.5 h-1.5 rounded-full bg-sky-500 flex-shrink-0" />
            )}
            <span className={msg.status === 'searching' ? 'text-yellow-700 dark:text-yellow-400' : 'text-sky-700 dark:text-sky-400'}>
              {msg.status === 'searching'
                ? `Searching${msg.query ? `: "${msg.query}"` : '...'}`
                : `Web search${msg.query ? `: "${msg.query}"` : ''}`}
            </span>
          </div>
          {hasResults && (
            <button
              onClick={() => setExpanded((v) => !v)}
              className="text-sky-600 dark:text-sky-400 hover:underline flex-shrink-0"
            >
              {expanded ? 'Hide' : `${(msg as { results?: SearchResult[] }).results!.length} sources`}
            </button>
          )}
        </div>

        {/* Expanded results */}
        {expanded && hasResults && (
          <div className="mt-2 space-y-2 border-t border-sky-200 dark:border-sky-800 pt-2">
            {(msg as { results: SearchResult[] }).results.map((r, i) => (
              <div key={i} className="space-y-0.5">
                <a
                  href={r.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sky-600 dark:text-sky-400 hover:underline truncate block"
                >
                  {r.url}
                </a>
                <p className="text-muted-foreground leading-snug line-clamp-3">{r.snippet}</p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

interface ConversationPanelProps {
  messages: ConversationMessage[]
  activeSpeaker: string | null
  status: StudioStatus
}

export function ConversationPanel({ messages, activeSpeaker, status }: ConversationPanelProps) {
  const bottomRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom on new messages / new tokens
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  if (messages.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-center p-8">
        <div className="space-y-2">
          <p className="text-muted-foreground text-sm">
            {status === 'connecting' ? 'Connecting...' : 'Configure your panel and click "Start Discussion"'}
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
      {messages.map((msg) => {
        if (msg.type === 'speaker') {
          const colors = SPEAKER_COLOR_CLASSES[msg.colorIndex] ?? SPEAKER_COLOR_CLASSES[0]
          return (
            <div key={msg.id} className="space-y-1">
              {/* Speaker name badge */}
              <div className="flex items-center gap-1.5">
                <span className={cn('text-xs font-semibold px-2 py-0.5 rounded-full', colors.badge)}>
                  {msg.speaker}
                </span>
              </div>
              {/* Bubble */}
              <div
                className={cn(
                  'rounded-2xl rounded-tl-sm border px-4 py-3 text-sm leading-relaxed max-w-[85%]',
                  colors.bubble,
                )}
              >
                {msg.text}
                {msg.streaming && (
                  <span className={cn('inline-block w-0.5 h-4 ml-0.5 align-middle animate-pulse rounded-full', colors.cursor)} />
                )}
              </div>
            </div>
          )
        }

        if (msg.type === 'user') {
          return (
            <div key={msg.id} className="flex justify-end">
              <div className="rounded-2xl rounded-tr-sm bg-muted border px-4 py-3 text-sm max-w-[75%]">
                {msg.text}
              </div>
            </div>
          )
        }

        if (msg.type === 'fact_check') {
          return <FactCheckCard key={msg.id} msg={msg} />
        }

        if (msg.type === 'system') {
          return (
            <div key={msg.id} className="flex justify-center">
              <span className="text-xs text-muted-foreground italic px-3 py-1">
                {msg.text}
              </span>
            </div>
          )
        }

        if (msg.type === 'consensus') {
          return (
            <div key={msg.id} className="rounded-xl border border-green-300 dark:border-green-700 bg-green-50 dark:bg-green-950/30 p-4 space-y-2">
              <div className="flex items-center gap-2">
                <span className="text-green-600 dark:text-green-400 text-sm font-semibold">
                  Panel reached consensus
                </span>
              </div>
              <div className="text-sm text-muted-foreground whitespace-pre-wrap leading-relaxed">
                {msg.summary}
              </div>
            </div>
          )
        }

        return null
      })}

      {/* Typing indicator when a speaker is active but bubble isn't created yet */}
      {activeSpeaker && messages.length > 0 && messages[messages.length - 1].type !== 'speaker' && (
        <div className="space-y-1">
          <div className="flex items-center gap-1.5">
            <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
              {activeSpeaker}
            </span>
          </div>
          <div className="flex gap-1 px-4 py-3 rounded-2xl rounded-tl-sm border bg-muted max-w-fit">
            <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground animate-bounce [animation-delay:0ms]" />
            <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground animate-bounce [animation-delay:150ms]" />
            <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground animate-bounce [animation-delay:300ms]" />
          </div>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  )
}
