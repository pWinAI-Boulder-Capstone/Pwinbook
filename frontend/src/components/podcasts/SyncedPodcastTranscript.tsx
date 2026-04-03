'use client'

import { useEffect, useMemo, useRef } from 'react'

import { cn } from '@/lib/utils'
import type { TranscriptEntry } from '@/lib/utils/podcast-episode'
import {
  buildWordTimings,
  getActiveWordGlobalIndex,
  tokenizeLine,
} from '@/lib/utils/podcast-transcript-sync'

interface SyncedPodcastTranscriptProps {
  entries: TranscriptEntry[]
  currentTime: number
  duration: number
  /** When false, highlight stays on the word for currentTime (frozen). */
  hasAudio: boolean
}

export function SyncedPodcastTranscript({
  entries,
  currentTime,
  duration,
  hasAudio,
}: SyncedPodcastTranscriptProps) {
  const timings = useMemo(
    () => buildWordTimings(entries, duration),
    [entries, duration]
  )

  const activeIdx = useMemo(() => {
    if (!hasAudio || timings.length === 0 || duration <= 0) return -1
    return getActiveWordGlobalIndex(currentTime, timings)
  }, [hasAudio, currentTime, duration, timings])

  const lines = useMemo(() => {
    let g = 0
    return entries.map((entry, lineIndex) => ({
      lineIndex,
      speaker: entry.speaker ?? 'Speaker',
      citation: entry.citation,
      words: tokenizeLine(entry.dialogue ?? entry.text ?? '').map((word) => ({
        word,
        globalIndex: g++,
      })),
    }))
  }, [entries])

  const lastScrolledWord = useRef(-1)
  useEffect(() => {
    lastScrolledWord.current = -1
  }, [entries, duration])

  useEffect(() => {
    if (activeIdx < 0) return
    if (activeIdx === lastScrolledWord.current) return
    lastScrolledWord.current = activeIdx
    const el = document.querySelector<HTMLElement>(
      `[data-podcast-sync-word="${activeIdx}"]`
    )
    el?.scrollIntoView({
      behavior: 'smooth',
      block: 'nearest',
      inline: 'nearest',
    })
  }, [activeIdx])

  return (
    <div className="space-y-3 p-4">
      {lines.map((line) => (
        <div
          key={line.lineIndex}
          data-podcast-sync-line={line.lineIndex}
          className="rounded-lg border bg-background p-3 text-sm shadow-sm"
        >
          <p className="font-semibold text-primary">{line.speaker}</p>
          <p className="mt-1 text-foreground/90 leading-relaxed">
            {line.words.length === 0 ? (
              <span className="text-muted-foreground">—</span>
            ) : (
              line.words.map(({ word, globalIndex }, i) => {
                const isActive = hasAudio && globalIndex === activeIdx
                return (
                  <span key={`${line.lineIndex}-${i}-${globalIndex}`} className="inline">
                    <span
                      data-podcast-sync-word={globalIndex}
                      className={cn(
                        'inline rounded-[3px] align-baseline transition-[background-color,box-shadow] duration-100',
                        'px-[2px] mx-px',
                        isActive && 'bg-primary/35 ring-1 ring-primary/50 ring-inset'
                      )}
                    >
                      {word}
                    </span>
                    {i < line.words.length - 1 ? ' ' : null}
                  </span>
                )
              })
            )}
          </p>
          {line.citation ? (
            <p className="mt-2 text-xs text-muted-foreground">{line.citation}</p>
          ) : null}
        </div>
      ))}
    </div>
  )
}
