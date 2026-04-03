'use client'

import { Pause, Play } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'

const RATES = ['0.75', '1', '1.25', '1.5', '1.75', '2']

function formatTime(seconds: number) {
  if (!Number.isFinite(seconds) || seconds < 0) {
    return '0:00'
  }
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

export interface PodcastPlayerBarProps {
  audioSrc?: string
  title: string
  thumbnailSrc?: string | null
  className?: string
  playing: boolean
  currentTime: number
  duration: number
  rate: string
  onRateChange: (rate: string) => void
  onTogglePlay: () => void
  onSkipBack: () => void
  onSkipForward: () => void
  onSeek: (progress0to1000: number) => void
  skipSeconds: number
}

export function PodcastPlayerBar({
  audioSrc,
  title,
  thumbnailSrc,
  className,
  playing,
  currentTime,
  duration,
  rate,
  onRateChange,
  onTogglePlay,
  onSkipBack,
  onSkipForward,
  onSeek,
  skipSeconds,
}: PodcastPlayerBarProps) {
  const remaining = Math.max(0, duration - currentTime)
  const progressPct =
    duration > 0 ? Math.min(1000, Math.round((currentTime / duration) * 1000)) : 0

  return (
    <div
      className={cn(
        'border-t bg-background/95 px-4 py-3 shadow-[0_-4px_24px_rgba(0,0,0,0.06)] backdrop-blur supports-[backdrop-filter]:bg-background/80',
        className
      )}
    >
      <div className="mx-auto flex max-w-6xl flex-col gap-3 sm:flex-row sm:items-center sm:gap-4">
        <div className="flex min-w-0 flex-1 items-center gap-3">
          <div className="h-14 w-14 shrink-0 overflow-hidden rounded-md border bg-muted">
            {thumbnailSrc ? (
              <img
                src={thumbnailSrc}
                alt=""
                className="h-full w-full object-cover"
              />
            ) : (
              <div className="flex h-full w-full items-center justify-center bg-gradient-to-br from-primary/20 to-primary/5 text-[10px] text-muted-foreground">
                Podcast
              </div>
            )}
          </div>
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-foreground">{title}</p>
            <p className="text-xs text-muted-foreground">
              {audioSrc ? 'Ready to play' : 'No audio file for this episode'}
            </p>
          </div>
        </div>

        <div className="flex flex-1 flex-col gap-2 sm:max-w-xl sm:flex-[1.5]">
          <div className="flex items-center justify-center gap-1 sm:gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-9 shrink-0 rounded-full px-2.5 text-xs font-medium"
              disabled={!audioSrc}
              onClick={onSkipBack}
              aria-label={`Go back ${skipSeconds} seconds`}
            >
              −{skipSeconds}s
            </Button>
            <Button
              type="button"
              size="icon"
              className="h-11 w-11 shrink-0 rounded-full"
              disabled={!audioSrc}
              onClick={onTogglePlay}
              aria-label={playing ? 'Pause' : 'Play'}
            >
              {playing ? (
                <Pause className="h-5 w-5" />
              ) : (
                <Play className="h-5 w-5 pl-0.5" />
              )}
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-9 shrink-0 rounded-full px-2.5 text-xs font-medium"
              disabled={!audioSrc}
              onClick={onSkipForward}
              aria-label={`Skip forward ${skipSeconds} seconds`}
            >
              +{skipSeconds}s
            </Button>
          </div>

          <div className="flex items-center gap-2">
            <span className="w-10 shrink-0 tabular-nums text-xs text-muted-foreground">
              {formatTime(currentTime)}
            </span>
            <input
              type="range"
              min={0}
              max={1000}
              step={1}
              value={progressPct}
              disabled={!audioSrc || duration <= 0}
              onChange={(e) => onSeek(Number(e.target.value))}
              className="h-2 flex-1 cursor-pointer accent-primary disabled:opacity-40"
              aria-label="Seek"
            />
            <span className="w-10 shrink-0 text-right tabular-nums text-xs text-muted-foreground">
              -{formatTime(remaining)}
            </span>
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 sm:w-36">
          <span className="text-xs text-muted-foreground">Speed</span>
          <Select value={rate} onValueChange={onRateChange} disabled={!audioSrc}>
            <SelectTrigger className="h-8 w-[88px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {RATES.map((r) => (
                <SelectItem key={r} value={r}>
                  {r}×
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
    </div>
  )
}
