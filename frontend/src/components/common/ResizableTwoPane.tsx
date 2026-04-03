'use client'

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { cn } from '@/lib/utils'

export interface ResizableTwoPaneProps {
  /** Unique key for persisting split position in localStorage */
  storageKey: string
  /** Left (primary) pane content */
  primary: ReactNode
  /** Right (secondary) pane content */
  secondary: ReactNode
  /** Initial left width as % of the row (used if nothing in localStorage) */
  defaultLeftPercent?: number
  /** Hard clamps in % (before pixel-based clamp) */
  minLeftPercent?: number
  maxLeftPercent?: number
  /** Keep at least this many px for the right pane while dragging */
  minRightPx?: number
  /** Keep at least this many px for the left pane while dragging */
  minLeftPx?: number
  className?: string
}

export function ResizableTwoPane({
  storageKey,
  primary,
  secondary,
  defaultLeftPercent = 58,
  minLeftPercent = 22,
  maxLeftPercent = 80,
  minRightPx = 280,
  minLeftPx = 240,
  className,
}: ResizableTwoPaneProps) {
  const [leftPercent, setLeftPercent] = useState(defaultLeftPercent)
  const [isDragging, setIsDragging] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const dragStartRef = useRef({ x: 0, percent: 0 })
  const latestPercentRef = useRef(leftPercent)

  const clampPercent = useCallback(
    (p: number) => {
      const el = containerRef.current
      if (!el) {
        return Math.min(maxLeftPercent, Math.max(minLeftPercent, p))
      }
      const W = el.getBoundingClientRect().width
      if (W < 1) {
        return Math.min(maxLeftPercent, Math.max(minLeftPercent, p))
      }
      const divider = 6
      // left pane width ≈ (p/100)*W; need ≥ minLeftPx and remainder − divider ≥ minRightPx
      const minL = Math.max(minLeftPercent, (minLeftPx / W) * 100)
      const maxL = Math.min(maxLeftPercent, ((W - divider - minRightPx) / W) * 100)
      if (maxL < minL) {
        return (minL + maxL) / 2
      }
      return Math.min(maxL, Math.max(minL, p))
    },
    [maxLeftPercent, minLeftPercent, minLeftPx, minRightPx]
  )

  useEffect(() => {
    try {
      const raw = localStorage.getItem(storageKey)
      if (raw === null || raw === '') return
      const n = Number.parseFloat(raw)
      if (!Number.isFinite(n)) return
      const clamped = Math.min(maxLeftPercent, Math.max(minLeftPercent, n))
      setLeftPercent(clamped)
      latestPercentRef.current = clamped
    } catch {
      /* ignore */
    }
  }, [storageKey, minLeftPercent, maxLeftPercent])

  useEffect(() => {
    latestPercentRef.current = leftPercent
  }, [leftPercent])

  const onMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault()
      dragStartRef.current = { x: e.clientX, percent: leftPercent }
      setIsDragging(true)
    },
    [leftPercent]
  )

  useEffect(() => {
    if (!isDragging) return

    const onMove = (e: MouseEvent) => {
      const el = containerRef.current
      if (!el) return
      const rect = el.getBoundingClientRect()
      const w = rect.width
      if (w < 1) return
      const dx = e.clientX - dragStartRef.current.x
      const deltaPct = (dx / w) * 100
      const start = dragStartRef.current.percent
      const next = clampPercent(start + deltaPct)
      latestPercentRef.current = next
      setLeftPercent(next)
    }

    const onUp = () => {
      setIsDragging(false)
      try {
        localStorage.setItem(storageKey, String(latestPercentRef.current))
      } catch {
        /* ignore */
      }
      document.body.style.removeProperty('user-select')
      document.body.style.removeProperty('cursor')
    }

    document.body.style.userSelect = 'none'
    document.body.style.cursor = 'col-resize'
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)

    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      document.body.style.removeProperty('user-select')
      document.body.style.removeProperty('cursor')
    }
  }, [isDragging, clampPercent, storageKey])

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'ArrowLeft') {
        e.preventDefault()
        setLeftPercent((p) => {
          const n = clampPercent(p - 1)
          try {
            localStorage.setItem(storageKey, String(n))
          } catch {
            /* ignore */
          }
          return n
        })
      } else if (e.key === 'ArrowRight') {
        e.preventDefault()
        setLeftPercent((p) => {
          const n = clampPercent(p + 1)
          try {
            localStorage.setItem(storageKey, String(n))
          } catch {
            /* ignore */
          }
          return n
        })
      }
    },
    [clampPercent, storageKey]
  )

  return (
    <div
      ref={containerRef}
      className={cn('flex min-h-0 w-full flex-1 flex-row', className)}
    >
      <div
        className="flex min-h-0 min-w-0 flex-col overflow-hidden"
        style={{ width: `${leftPercent}%` }}
      >
        {primary}
      </div>
      <div
        role="separator"
        aria-label="Resize between main content and chat"
        title="Drag to resize panels"
        aria-orientation="vertical"
        aria-valuenow={Math.round(leftPercent)}
        aria-valuemin={minLeftPercent}
        aria-valuemax={maxLeftPercent}
        tabIndex={0}
        onMouseDown={onMouseDown}
        onKeyDown={onKeyDown}
        className={cn(
          'flex w-1.5 shrink-0 cursor-col-resize items-center justify-center border-x border-border/60 bg-muted/40 transition-colors hover:bg-primary/15 focus-visible:bg-primary/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
          isDragging && 'bg-primary/25'
        )}
      >
        <span
          className="h-10 w-px rounded-full bg-muted-foreground/35"
          aria-hidden
        />
      </div>
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
        {secondary}
      </div>
    </div>
  )
}
