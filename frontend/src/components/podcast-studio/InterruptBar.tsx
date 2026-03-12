'use client'

import { KeyboardEvent, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import type { StudioStatus } from '@/lib/types/podcast-studio-ws'

interface InterruptBarProps {
  activeSpeaker: string | null
  status: StudioStatus
  onInterrupt: (message: string) => void
  onStop: () => void
}

export function InterruptBar({ activeSpeaker, status, onInterrupt, onStop }: InterruptBarProps) {
  const [text, setText] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const disabled = status === 'idle' || status === 'done' || status === 'error' || status === 'connecting'

  const handleSend = () => {
    const trimmed = text.trim()
    if (!trimmed || disabled) return
    onInterrupt(trimmed)
    setText('')
    textareaRef.current?.focus()
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const speakerLabel = activeSpeaker
    ? `${activeSpeaker} is talking...`
    : status === 'fact_checking'
    ? 'Checking sources...'
    : status === 'consensus_checking'
    ? 'Checking consensus...'
    : status === 'active'
    ? 'Panel is thinking...'
    : null

  return (
    <div className="border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 px-4 py-3 space-y-2">
      {/* Speaker status */}
      {speakerLabel && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="inline-flex gap-0.5">
            <span className="w-1 h-1 rounded-full bg-current animate-bounce [animation-delay:0ms]" />
            <span className="w-1 h-1 rounded-full bg-current animate-bounce [animation-delay:150ms]" />
            <span className="w-1 h-1 rounded-full bg-current animate-bounce [animation-delay:300ms]" />
          </span>
          {speakerLabel}
        </div>
      )}

      {/* Input row */}
      <div className="flex gap-2 items-end">
        <Textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            disabled
              ? 'Start a discussion to enable interrupts'
              : "Interrupt the panel — challenge a claim, ask a question, or steer the discussion..."
          }
          disabled={disabled}
          rows={2}
          className={cn(
            'flex-1 resize-none text-sm min-h-[60px] max-h-[120px]',
            disabled && 'opacity-50',
          )}
        />
        <div className="flex flex-col gap-1.5 pb-0.5">
          <Button
            onClick={handleSend}
            disabled={disabled || !text.trim()}
            size="sm"
            className="h-8"
          >
            Interrupt
          </Button>
          {status === 'active' || status === 'fact_checking' || status === 'consensus_checking' ? (
            <Button
              variant="outline"
              size="sm"
              onClick={onStop}
              className="h-8 text-destructive hover:text-destructive"
            >
              Stop
            </Button>
          ) : null}
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        Press Enter to send · Shift+Enter for new line · Message takes effect after the current speaker finishes
      </p>
    </div>
  )
}
