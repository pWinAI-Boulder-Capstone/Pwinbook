'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { ArrowLeft, ChevronLeft, ChevronRight, Loader2, List, RefreshCw } from 'lucide-react'

import { AppShell } from '@/components/layout/AppShell'
import { PodcastPlayerBar } from '@/components/podcasts/PodcastPlayerBar'
import { SyncedPodcastTranscript } from '@/components/podcasts/SyncedPodcastTranscript'
import { Button } from '@/components/ui/button'
import { usePodcastAudioPlayback } from '@/lib/hooks/usePodcastAudioPlayback'
import { podcastsApi } from '@/lib/api/podcasts'
import { QUERY_KEYS } from '@/lib/api/query-client'
import { usePodcastEpisode } from '@/lib/hooks/use-podcasts'
import { usePodcastEpisodeAudio } from '@/lib/hooks/usePodcastEpisodeAudio'
import {
  extractTranscriptEntries,
  getTranscriptMeta,
} from '@/lib/utils/podcast-episode'
import { Badge } from '@/components/ui/badge'

export default function PodcastEpisodePage() {
  const params = useParams()
  const router = useRouter()
  const rawId = params.id as string
  const episodeId = useMemo(() => decodeURIComponent(rawId), [rawId])

  const queryClient = useQueryClient()
  const { data: episode, isLoading, isError, error } = usePodcastEpisode(episodeId)
  const { audioSrc, audioError } = usePodcastEpisodeAudio(episode)
  const playback = usePodcastAudioPlayback(audioSrc)

  const [outlineOpen, setOutlineOpen] = useState(false)
  const [coverUrl, setCoverUrl] = useState<string | null>(null)
  const [coverLoading, setCoverLoading] = useState(false)
  const [coverRegenerating, setCoverRegenerating] = useState(false)
  const [coverError, setCoverError] = useState<string | null>(null)
  const coverFetchedRef = useRef(false)

  const transcriptEntries = useMemo(
    () => (episode ? extractTranscriptEntries(episode.transcript) : []),
    [episode]
  )

  const transcriptMeta = useMemo(
    () => (episode ? getTranscriptMeta(episode.transcript) : {}),
    [episode]
  )

  useEffect(() => {
    if (!episode) return

    const t = episode.transcript as Record<string, unknown> | null | undefined
    const existing = t?.cover_image_data_url
    if (typeof existing === 'string' && existing.startsWith('data:image/')) {
      setCoverUrl(existing)
      setCoverError(null)
      setCoverLoading(false)
      coverFetchedRef.current = true
      return
    }

    // Only attempt generation once per page load to avoid duplicate requests
    if (coverFetchedRef.current) return
    coverFetchedRef.current = true

    let cancelled = false
    setCoverLoading(true)
    setCoverError(null)

    ;(async () => {
      try {
        const res = await podcastsApi.generateEpisodeCover(episode.id)
        if (cancelled) return
        if (res.image_data_url) {
          setCoverUrl(res.image_data_url)
        } else if (res.error) {
          setCoverError(res.error)
        }
      } catch {
        if (!cancelled) {
          setCoverError('Could not generate cover image')
        }
      } finally {
        if (!cancelled) setCoverLoading(false)
      }
    })()

    return () => {
      cancelled = true
    }
  }, [episode])

  const handleRegenerateCover = useCallback(async () => {
    if (!episode) return
    coverFetchedRef.current = true  // prevent auto-fetch race if episode refetches
    setCoverRegenerating(true)
    setCoverError(null)
    try {
      const res = await podcastsApi.generateEpisodeCover(episode.id, true)
      if (res.image_data_url) {
        setCoverUrl(res.image_data_url)
        await queryClient.invalidateQueries({
          queryKey: QUERY_KEYS.podcastEpisode(episodeId),
        })
        await queryClient.invalidateQueries({ queryKey: QUERY_KEYS.podcastEpisodes })
      } else if (res.error) {
        setCoverError(res.error)
      }
    } catch {
      setCoverError('Could not regenerate cover image')
    } finally {
      setCoverRegenerating(false)
    }
  }, [episode, episodeId, queryClient])

  const handleSeekSeconds = useCallback(
    (timeSeconds: number) => {
      const a = playback.audioRef.current
      if (!a || !Number.isFinite(a.duration) || a.duration <= 0) return
      a.currentTime = Math.max(0, Math.min(a.duration, timeSeconds))
    },
    [playback.audioRef]
  )

  return (
    <AppShell>
      <div className="relative flex min-h-0 flex-1 flex-col">
        {/* ── Full-page background cover image ── */}
        {coverUrl && (
          <div className="pointer-events-none absolute inset-0 z-0">
            <img
              src={coverUrl}
              alt=""
              className="h-full w-full object-cover"
            />
            {/* Dark + blur overlay for readability */}
            <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
          </div>
        )}

        {/* ── Top bar ── */}
        <div className="relative z-10 flex shrink-0 items-center gap-3 border-b border-white/10 bg-black/30 px-4 py-3 backdrop-blur-md">
          <Button variant="ghost" size="sm" asChild className="gap-2 text-white/80 hover:text-white hover:bg-white/10">
            <Link href="/podcasts">
              <ArrowLeft className="h-4 w-4" />
              Episodes
            </Link>
          </Button>
        </div>

        {isLoading ? (
          <div className="relative z-10 flex flex-1 items-center justify-center gap-2 text-white/60">
            <Loader2 className="h-5 w-5 animate-spin" />
            Loading episode…
          </div>
        ) : isError || !episode ? (
          <div className="relative z-10 flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
            <p className="text-sm text-white/60">
              {error instanceof Error ? error.message : 'Episode not found.'}
            </p>
            <Button variant="outline" onClick={() => router.push('/podcasts')}>
              Back to podcasts
            </Button>
          </div>
        ) : (
          <>
            {/* All content layered above the background */}
            <div className="relative z-10 flex min-h-0 flex-1 flex-col overflow-y-auto">
              {/* ── Glassmorphic episode header ── */}
              <div className="shrink-0 border-b border-white/5">
                <div className="mx-auto flex max-w-3xl items-center gap-4 px-4 py-5 sm:px-6 md:gap-6 md:py-8">
                  {/* Cover art thumbnail */}
                  <div className="h-20 w-20 shrink-0 overflow-hidden rounded-xl shadow-2xl ring-1 ring-white/20 sm:h-24 sm:w-24 md:h-28 md:w-28">
                    {coverUrl ? (
                      <img
                        src={coverUrl}
                        alt=""
                        className="h-full w-full object-cover"
                      />
                    ) : coverLoading ? (
                      <div className="flex h-full w-full items-center justify-center bg-white/5">
                        <Loader2 className="h-6 w-6 animate-spin text-white/40" />
                      </div>
                    ) : (
                      <div className="flex h-full w-full items-center justify-center bg-white/5">
                        <span className="text-[10px] text-white/40">
                          Podcast
                        </span>
                      </div>
                    )}
                  </div>
                  {/* Title & metadata */}
                  <div className="min-w-0 flex-1">
                    <h1 className="text-xl font-bold leading-tight text-white sm:text-2xl md:text-3xl">
                      {episode.name}
                    </h1>
                    <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-white/50">
                      {transcriptEntries.length > 0 && (
                        <span>{transcriptEntries.length} lines</span>
                      )}
                      {playback.duration > 0 && (
                        <>
                          <span className="text-white/30">·</span>
                          <span>
                            {Math.floor(playback.duration / 60)}m{' '}
                            {Math.floor(playback.duration % 60)}s
                          </span>
                        </>
                      )}
                    </div>
                    <div className="mt-2 flex items-center gap-2">
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-7 gap-1.5 px-2 text-xs text-white/60 hover:text-white hover:bg-white/10"
                        disabled={coverRegenerating || coverLoading}
                        onClick={handleRegenerateCover}
                      >
                        {coverRegenerating ? (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        ) : (
                          <RefreshCw className="h-3 w-3" />
                        )}
                        New cover
                      </Button>
                      {(coverLoading || coverRegenerating) && (
                        <span className="flex items-center gap-1.5 text-xs text-white/50">
                          <Loader2 className="h-3 w-3 animate-spin" />
                          {coverRegenerating ? 'Regenerating…' : 'Generating cover art…'}
                        </span>
                      )}
                      {coverError && !coverLoading && !coverRegenerating && (
                        <span className="text-xs text-red-400">
                          Cover art failed — try &quot;New cover&quot;
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </div>

              {/* Horizontal layout: optional outline side-panel + transcript */}
              <div className="flex min-h-0 flex-1">
                {/* Outline side panel */}
                {episode.outline &&
                  typeof episode.outline === 'object' &&
                  Array.isArray((episode.outline as Record<string, unknown>).segments) &&
                  ((episode.outline as Record<string, unknown>).segments as unknown[]).length > 0 && (
                    <>
                      <div
                        className={`shrink-0 border-r border-white/10 bg-black/30 backdrop-blur-lg transition-[width] duration-300 ease-in-out overflow-hidden ${
                          outlineOpen ? 'w-152' : 'w-0'
                        }`}
                      >
                        <div className="flex h-full w-152 flex-col">
                          <div className="flex items-center justify-between border-b border-white/10 px-4 py-3">
                            <div className="flex items-center gap-2">
                              <List className="h-4 w-4 text-white/50" />
                              <span className="text-sm font-semibold text-white">Outline</span>
                              <Badge variant="secondary" className="text-[10px]">
                                {((episode.outline as Record<string, unknown>).segments as unknown[]).length}
                              </Badge>
                            </div>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-7 w-7"
                              onClick={() => setOutlineOpen(false)}
                            >
                              <ChevronLeft className="h-4 w-4" />
                            </Button>
                          </div>
                          <div className="flex-1 overflow-y-auto scrollbar-hide p-3 space-y-2">
                            {((episode.outline as Record<string, unknown>).segments as Array<{ name?: string; description?: string; size?: string }>).map(
                              (seg, idx) => (
                                <div
                                  key={idx}
                                  className="rounded-lg border border-white/10 bg-white/5 px-3 py-2.5"
                                >
                                  <div className="flex items-start gap-2">
                                    <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-white/10 text-[10px] font-semibold text-white/80">
                                      {idx + 1}
                                    </span>
                                    <div className="min-w-0 flex-1">
                                      <div className="flex items-center gap-1.5">
                                        <span className="text-sm font-medium leading-snug text-white/90">
                                          {seg.name ?? `Segment ${idx + 1}`}
                                        </span>
                                        {seg.size && (
                                          <Badge variant="outline" className="ml-auto shrink-0 text-[9px] uppercase">
                                            {seg.size}
                                          </Badge>
                                        )}
                                      </div>
                                      {seg.description && (
                                        <p className="mt-1 text-xs leading-relaxed text-white/50">
                                          {seg.description}
                                        </p>
                                      )}
                                    </div>
                                  </div>
                                </div>
                              )
                            )}
                          </div>
                        </div>
                      </div>

                      {/* Toggle button — visible when panel is closed */}
                      {!outlineOpen && (
                        <div className="flex shrink-0 items-start border-r border-white/10">
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-auto rounded-none px-2.5 py-4 text-white/50 hover:bg-white/10 hover:text-white"
                            onClick={() => setOutlineOpen(true)}
                            title="Show outline"
                          >
                            <div className="flex flex-col items-center gap-2">
                              <ChevronRight className="h-4 w-4" />
                              <span className="text-xs font-medium tracking-wide [writing-mode:vertical-lr]">
                                Outline
                              </span>
                            </div>
                          </Button>
                        </div>
                      )}
                    </>
                  )}

                {/* Transcript — fills remaining space */}
                <div className="min-w-0 flex-1 overflow-y-auto scrollbar-hide">
                {transcriptMeta.audioError ? (
                  <div className="mx-auto max-w-3xl px-4 pt-4 sm:px-6">
                    <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-xs text-destructive">
                      Audio generation failed: {transcriptMeta.audioError}
                    </div>
                  </div>
                ) : null}

                {transcriptEntries.length > 0 ? (
                  <div className="mx-auto max-w-3xl">
                    <SyncedPodcastTranscript
                      entries={transcriptEntries}
                      currentTime={playback.currentTime}
                      duration={playback.duration}
                      hasAudio={Boolean(audioSrc && playback.duration > 0)}
                      onSeek={handleSeekSeconds}
                      storedLineTimings={transcriptMeta.durationInfo?.line_timings}
                    />
                  </div>
                ) : (
                  <p className="mx-auto max-w-3xl px-4 py-8 text-center text-sm text-white/50 sm:px-6">
                    No transcript lines yet. If generation is still running, check
                    back shortly.
                  </p>
                )}

                {/* Bottom padding so transcript doesn't hide behind player bar */}
                <div className="h-32" />
                </div>
              </div>
            </div>

            {audioError ? (
              <p className="relative z-10 shrink-0 border-t border-white/10 bg-red-900/30 backdrop-blur-md px-4 py-2 text-center text-xs text-red-300">
                {audioError}
              </p>
            ) : null}

            {audioSrc ? (
              <audio
                key={audioSrc}
                ref={playback.audioRef}
                src={audioSrc}
                preload="metadata"
                className="hidden"
              />
            ) : null}

            <PodcastPlayerBar
              className="relative z-10 border-t border-white/10 bg-black/40 backdrop-blur-xl"
              audioSrc={audioSrc}
              title={episode.name}
              thumbnailSrc={coverUrl}
              playing={playback.playing}
              currentTime={playback.currentTime}
              duration={playback.duration}
              rate={playback.rate}
              onRateChange={playback.setRate}
              onTogglePlay={playback.togglePlay}
              onSkipBack={playback.skipBack}
              onSkipForward={playback.skipForward}
              onSeek={playback.seekToProgress}
              skipSeconds={playback.skipSeconds}
            />
          </>
        )}
      </div>
    </AppShell>
  )
}
