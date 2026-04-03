'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { ArrowLeft, Loader2 } from 'lucide-react'

import { AppShell } from '@/components/layout/AppShell'
import { PodcastCoverHero } from '@/components/podcasts/PodcastCoverHero'
import { PodcastPlayerBar } from '@/components/podcasts/PodcastPlayerBar'
import { SyncedPodcastTranscript } from '@/components/podcasts/SyncedPodcastTranscript'
import { Button } from '@/components/ui/button'
import { usePodcastAudioPlayback } from '@/lib/hooks/usePodcastAudioPlayback'
import { usePodcastWebAudioAnalyser } from '@/lib/hooks/usePodcastWebAudioAnalyser'
import { ScrollArea } from '@/components/ui/scroll-area'
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
  const { analyserRef } = usePodcastWebAudioAnalyser(playback.audioRef, audioSrc)

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

  return (
    <AppShell>
      <div className="flex min-h-0 flex-1 flex-col">
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
            <div className="grid min-h-0 flex-1 lg:grid-cols-2">
              <div className="relative flex min-h-[320px] flex-col border-b lg:min-h-0 lg:border-b-0 lg:border-r">
                <PodcastCoverHero
                  title={episode.name}
                  coverUrl={coverUrl}
                  coverLoading={coverLoading}
                  coverError={coverError}
                  analyserRef={analyserRef}
                  audioSrc={audioSrc}
                  isPlaying={playback.playing}
                  onRegenerateCover={handleRegenerateCover}
                  regenerateCoverPending={coverRegenerating}
                />
              </div>

              <div className="flex min-h-0 min-w-0 flex-col bg-muted/20">
                <div className="border-b px-4 py-2">
                  <h2 className="text-sm font-medium text-foreground">Transcript</h2>
                  <p className="text-xs text-muted-foreground">
                    Generated dialogue for this episode
                  </p>
                </div>
                <ScrollArea className="min-h-[320px] flex-1 lg:max-h-[calc(100vh-13rem)]">
                  {transcriptMeta.audioError ? (
                    <div className="p-4">
                      <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-xs text-destructive">
                        Audio generation failed: {transcriptMeta.audioError}
                      </div>
                    </div>
                  ) : null}
                  {transcriptEntries.length > 0 ? (
                    <SyncedPodcastTranscript
                      entries={transcriptEntries}
                      currentTime={playback.currentTime}
                      duration={playback.duration}
                      hasAudio={Boolean(audioSrc && playback.duration > 0)}
                    />
                  ) : (
                    <p className="p-4 text-sm text-muted-foreground">
                      No transcript lines yet. If generation is still running, check
                      back shortly.
                    </p>
                  )}
                </ScrollArea>
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
