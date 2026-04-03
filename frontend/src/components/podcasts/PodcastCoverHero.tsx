'use client'

import type { RefObject } from 'react'
import { Loader2 } from 'lucide-react'

import { CircularSpectrumVisualizer } from '@/components/podcasts/CircularSpectrumVisualizer'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const HERO_VISUALIZER_PX = 320

interface PodcastCoverHeroProps {
  title: string
  coverUrl: string | null
  coverLoading: boolean
  coverError: string | null
  analyserRef: RefObject<AnalyserNode | null>
  audioSrc: string | undefined
  isPlaying: boolean
  /** Bottom-right: request a new cover from the server (uses episode source + transcript). */
  onRegenerateCover?: () => void
  regenerateCoverPending?: boolean
  className?: string
}

export function PodcastCoverHero({
  title,
  coverUrl,
  coverLoading,
  coverError,
  analyserRef,
  audioSrc,
  isPlaying,
  onRegenerateCover,
  regenerateCoverPending = false,
  className,
}: PodcastCoverHeroProps) {
  const hasArt = Boolean(coverUrl)

  return (
    <div
      className={cn(
        'relative flex min-h-[320px] flex-1 flex-col overflow-hidden lg:min-h-0',
        className
      )}
    >
      {coverLoading && !coverUrl ? (
        <div className="absolute inset-0 z-0 flex items-center justify-center bg-muted/50">
          <Loader2 className="h-10 w-10 animate-spin text-muted-foreground" />
        </div>
      ) : hasArt ? (
        <img
          src={coverUrl!}
          alt=""
          className="absolute inset-0 z-0 h-full w-full object-cover"
        />
      ) : (
        <div
          className="absolute inset-0 z-0 bg-gradient-to-br from-primary/20 via-muted to-primary/10"
          aria-hidden
        />
      )}

      {/* Light white wash (reference: soft fade over artwork) */}
      <div
        className="pointer-events-none absolute inset-0 z-[1] bg-gradient-to-b from-white/50 via-white/28 to-white/12"
        aria-hidden
      />
      <div
        className="pointer-events-none absolute inset-0 z-[1] bg-white/15"
        aria-hidden
      />

      {/* Title — top, above fade visually */}
      <div className="relative z-10 px-6 pb-2 pt-6">
        <h1 className="max-w-[95%] text-3xl font-semibold uppercase leading-tight tracking-wide text-foreground drop-shadow-md md:text-4xl">
          {title}
        </h1>
      </div>

      {/* Center: circular art + spectrum ring */}
      <div className="relative z-10 flex flex-1 flex-col items-center justify-center px-4 pb-10 pt-4">
        <div className="relative flex h-[min(72vw,320px)] w-[min(72vw,320px)] max-w-[90vw] items-center justify-center sm:h-[280px] sm:w-[280px] md:h-[300px] md:w-[300px]">
          <div className="absolute inset-0 flex items-center justify-center">
            <CircularSpectrumVisualizer
              analyserRef={analyserRef}
              isPlaying={Boolean(audioSrc && isPlaying)}
              size={HERO_VISUALIZER_PX}
              className="max-h-full max-w-full opacity-95"
            />
          </div>

          <div className="relative z-[2] flex h-[58%] w-[58%] items-center justify-center sm:h-[60%] sm:w-[60%]">
            {hasArt ? (
              <img
                src={coverUrl!}
                alt=""
                className="h-full w-full rounded-full object-cover shadow-2xl ring-[5px] ring-white/90 ring-offset-2 ring-offset-transparent"
              />
            ) : (
              <div className="flex h-full w-full items-center justify-center rounded-full bg-gradient-to-br from-primary/30 to-muted ring-[5px] ring-white/80 shadow-xl">
                <span className="px-4 text-center text-sm font-medium text-muted-foreground">
                  {coverError ? 'No cover' : 'Podcast'}
                </span>
              </div>
            )}
          </div>
        </div>

        {coverError && !hasArt ? (
          <p className="relative z-10 mt-2 max-w-sm text-center text-xs text-muted-foreground">
            {coverError}
          </p>
        ) : null}
      </div>

      {/* Bottom readability strip */}
      <div
        className="pointer-events-none absolute inset-x-0 bottom-0 z-[1] h-24 bg-gradient-to-t from-background/40 to-transparent"
        aria-hidden
      />

      {onRegenerateCover ? (
        <div className="absolute bottom-4 right-4 z-20 flex max-w-[min(calc(100%-2rem),240px)] flex-col items-end gap-2">
          {coverError && hasArt ? (
            <p
              role="alert"
              className="rounded-md border border-destructive/35 bg-background/90 px-2 py-1.5 text-right text-xs text-destructive shadow-sm backdrop-blur-sm"
            >
              {coverError}
            </p>
          ) : null}
          <Button
            type="button"
            variant="secondary"
            size="sm"
            className="gap-2 bg-background/85 shadow-md backdrop-blur-sm hover:bg-background/95"
            disabled={regenerateCoverPending || coverLoading}
            onClick={onRegenerateCover}
          >
            {regenerateCoverPending ? (
              <Loader2 className="h-4 w-4 shrink-0 animate-spin" aria-hidden />
            ) : null}
            <span className="hidden sm:inline">Regenerate image</span>
            <span className="sm:hidden">New image</span>
          </Button>
        </div>
      ) : null}
    </div>
  )
}
