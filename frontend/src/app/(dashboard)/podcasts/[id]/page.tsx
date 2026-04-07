'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { ArrowLeft, Loader2, RefreshCw } from 'lucide-react'

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

export default function PodcastEpisodePage() {
  const params = useParams()
  const router = useRouter()
  const rawId = params.id as string
  const episodeId = useMemo(() => decodeURIComponent(rawId), [rawId])

  const queryClient = useQueryClient()
  const { data: episode, isLoading, isError, error } = usePodcastEpisode(episodeId)
  const { audioSrc, audioError } = usePodcastEpisodeAudio(episode)
  const playback = usePodcastAudioPlayback(audioSrc)

  const [coverUrl, setCoverUrl] = useState<string | null>(null)
  const [coverLoading, setCoverLoading] = useState(false)
  const [coverRegenerating, setCoverRegenerating] = useState(false)
  const [coverError, setCoverError] = useState<string | null>(null)

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
      return
    }

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
      <div className="flex min-h-0 flex-1 flex-col">
        {/* Compact top bar with back button + episode info */}
        <div className="flex shrink-0 items-center gap-3 border-b px-4 py-3">
          <Button variant="ghost" size="sm" asChild className="gap-2">
            <Link href="/podcasts">
              <ArrowLeft className="h-4 w-4" />
              Episodes
            </Link>
          </Button>
        </div>

        {isLoading ? (
          <div className="flex flex-1 items-center justify-center gap-2 text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin" />
            Loading episode…
          </div>
        ) : isError || !episode ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
            <p className="text-sm text-muted-foreground">
              {error instanceof Error ? error.message : 'Episode not found.'}
            </p>
            <Button variant="outline" onClick={() => router.push('/podcasts')}>
              Back to podcasts
            </Button>
          </div>
        ) : (
          <>
            {/* Illuminate-style layout: compact header + full-width transcript */}
            <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
              {/* Compact episode header with cover art */}
              <div className="relative shrink-0 border-b bg-gradient-to-b from-primary/5 to-background">
                <div className="mx-auto flex max-w-3xl items-center gap-4 px-4 py-5 sm:px-6 md:gap-6 md:py-8">
                  {/* Cover art thumbnail */}
                  <div className="h-20 w-20 shrink-0 overflow-hidden rounded-xl bg-muted shadow-lg ring-1 ring-black/5 sm:h-24 sm:w-24 md:h-28 md:w-28">
                    {coverUrl ? (
                      <img
                        src={coverUrl}
                        alt=""
                        className="h-full w-full object-cover"
                      />
                    ) : coverLoading ? (
                      <div className="flex h-full w-full items-center justify-center">
                        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                      </div>
                    ) : (
                      <div className="flex h-full w-full items-center justify-center bg-gradient-to-br from-primary/20 to-primary/5">
                        <span className="text-[10px] text-muted-foreground">
                          Podcast
                        </span>
                      </div>
                    )}
                  </div>
                  {/* Title & metadata */}
                  <div className="min-w-0 flex-1">
                    <h1 className="text-xl font-bold leading-tight text-foreground sm:text-2xl md:text-3xl">
                      {episode.name}
                    </h1>
                    <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                      {transcriptEntries.length > 0 && (
                        <span>{transcriptEntries.length} lines</span>
                      )}
                      {playback.duration > 0 && (
                        <>
                          <span className="text-muted-foreground/40">·</span>
                          <span>
                            {Math.floor(playback.duration / 60)}m{' '}
                            {Math.floor(playback.duration % 60)}s
                          </span>
                        </>
                      )}
                    </div>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="mt-2 h-7 gap-1.5 px-2 text-xs text-muted-foreground hover:text-foreground"
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
                  </div>
                </div>
              </div>

              {/* Transcript — Illuminate-style centered scroll */}
              <div className="flex-1">
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
                    />
                  </div>
                ) : (
                  <p className="mx-auto max-w-3xl px-4 py-8 text-center text-sm text-muted-foreground sm:px-6">
                    No transcript lines yet. If generation is still running, check
                    back shortly.
                  </p>
                )}

                {/* Bottom padding so transcript doesn't hide behind player bar */}
                <div className="h-32" />
              </div>
            </div>

            {audioError ? (
              <p className="shrink-0 border-t bg-destructive/10 px-4 py-2 text-center text-xs text-destructive">
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
