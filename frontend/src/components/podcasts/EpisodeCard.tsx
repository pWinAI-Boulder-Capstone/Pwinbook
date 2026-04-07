'use client'

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { formatDistanceToNow } from 'date-fns'
import { Clock, Loader2, Mic, Play, Trash2 } from 'lucide-react'

import { EpisodeStatus, PodcastEpisode } from '@/lib/types/podcasts'
import { podcastsApi } from '@/lib/api/podcasts'
import { cn } from '@/lib/utils'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'

interface EpisodeCardProps {
  episode: PodcastEpisode
  onDelete: (episodeId: string) => Promise<void> | void
  deleting?: boolean
}

const STATUS_META: Record<
  EpisodeStatus | 'unknown',
  { label: string; className: string; iconColor: string }
> = {
  running: {
    label: 'Processing',
    className: 'bg-amber-100 text-amber-800 border-amber-200',
    iconColor: 'text-amber-500',
  },
  processing: {
    label: 'Processing',
    className: 'bg-amber-100 text-amber-800 border-amber-200',
    iconColor: 'text-amber-500',
  },
  completed: {
    label: 'Completed',
    className: 'bg-emerald-100 text-emerald-800 border-emerald-200',
    iconColor: 'text-emerald-500',
  },
  failed: {
    label: 'Failed',
    className: 'bg-red-100 text-red-800 border-red-200',
    iconColor: 'text-red-500',
  },
  error: {
    label: 'Failed',
    className: 'bg-red-100 text-red-800 border-red-200',
    iconColor: 'text-red-500',
  },
  pending: {
    label: 'Pending',
    className: 'bg-sky-100 text-sky-800 border-sky-200',
    iconColor: 'text-sky-500',
  },
  submitted: {
    label: 'Pending',
    className: 'bg-sky-100 text-sky-800 border-sky-200',
    iconColor: 'text-sky-500',
  },
  unknown: {
    label: 'Unknown',
    className: 'bg-muted text-muted-foreground border-transparent',
    iconColor: 'text-muted-foreground',
  },
}

const STATUS_GRADIENT: Record<EpisodeStatus | 'unknown', string> = {
  running: 'from-amber-500/20 to-orange-500/10',
  processing: 'from-amber-500/20 to-orange-500/10',
  completed: 'from-emerald-500/20 to-teal-500/10',
  failed: 'from-red-500/20 to-rose-500/10',
  error: 'from-red-500/20 to-rose-500/10',
  pending: 'from-sky-500/20 to-blue-500/10',
  submitted: 'from-sky-500/20 to-blue-500/10',
  unknown: 'from-muted/50 to-muted/30',
}

export function EpisodeCard({ episode, onDelete, deleting }: EpisodeCardProps) {
  const status = episode.job_status ?? 'unknown'
  const meta = STATUS_META[status]
  const gradient = STATUS_GRADIENT[status]

  // Extract cached cover from transcript data
  const cachedCover = (() => {
    const t = episode.transcript as Record<string, unknown> | null | undefined
    const url = t?.cover_image_data_url
    return typeof url === 'string' && url.startsWith('data:image/') ? url : null
  })()

  const [coverUrl, setCoverUrl] = useState<string | null>(cachedCover)
  const [coverLoading, setCoverLoading] = useState(false)
  const generationAttempted = useRef(false)

  // Sync cover from refetched episode data (e.g. background generation finished)
  useEffect(() => {
    if (cachedCover && !coverUrl) {
      setCoverUrl(cachedCover)
      setCoverLoading(false)
    }
  }, [cachedCover, coverUrl])

  // Lazily generate cover for completed episodes that don't have one
  useEffect(() => {
    if (coverUrl || generationAttempted.current) return
    if (status !== 'completed') return

    generationAttempted.current = true
    setCoverLoading(true)

    let cancelled = false
    ;(async () => {
      try {
        const res = await podcastsApi.generateEpisodeCover(episode.id)
        if (cancelled) return
        if (res.image_data_url) {
          setCoverUrl(res.image_data_url)
        }
      } catch {
        // Silently ignore — tile falls back to gradient
      } finally {
        if (!cancelled) setCoverLoading(false)
      }
    })()

    return () => { cancelled = true }
  }, [coverUrl, status, episode.id])

  const createdLabel = episode.created
    ? formatDistanceToNow(new Date(episode.created), { addSuffix: true })
    : null

  const handleDelete = (e: React.MouseEvent) => {
    e.stopPropagation()
    void onDelete(episode.id)
  }

  return (
    <div className="group relative flex flex-col overflow-hidden rounded-xl border bg-card shadow-sm transition-all hover:shadow-md hover:-translate-y-0.5">
      {/* Cover image or gradient header */}
      <Link
        href={`/podcasts/${encodeURIComponent(episode.id)}`}
        className="block"
      >
        <div
          className={cn(
            'relative flex h-36 items-center justify-center overflow-hidden',
            !coverUrl && `bg-gradient-to-br ${gradient}`
          )}
        >
          {coverUrl ? (
            <>
              <img
                src={coverUrl}
                alt=""
                className="absolute inset-0 h-full w-full object-cover"
              />
              {/* Subtle overlay so the icon remains readable */}
              <div className="absolute inset-0 bg-black/20" />
            </>
          ) : null}

          {/* Loading spinner for cover generation */}
          {coverLoading && !coverUrl && (
            <div className="absolute inset-0 flex items-center justify-center bg-muted/30">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          )}

          {/* Center icon */}
          <div
            className={cn(
              'relative z-10 flex h-14 w-14 items-center justify-center rounded-full shadow-sm backdrop-blur-sm',
              coverUrl
                ? 'bg-black/40 text-white'
                : 'bg-background/80',
              status === 'completed' && !coverUrl && 'ring-2 ring-emerald-400/40'
            )}
          >
            {status === 'completed' ? (
              <Play className={cn('h-6 w-6 ml-0.5', coverUrl ? 'text-white' : 'text-emerald-600')} />
            ) : (
              <Mic className={cn('h-6 w-6', coverUrl ? 'text-white' : meta.iconColor)} />
            )}
          </div>

          {/* Status badge overlay */}
          {status !== 'completed' && (
            <Badge
              variant="outline"
              className={cn(
                'absolute top-2.5 right-2.5 text-[10px] uppercase tracking-wide',
                meta.className
              )}
            >
              {meta.label}
            </Badge>
          )}
        </div>
      </Link>

      {/* Card body */}
      <div className="flex flex-1 flex-col gap-2 p-4">
        <Link
          href={`/podcasts/${encodeURIComponent(episode.id)}`}
          className="line-clamp-2 text-sm font-semibold leading-snug text-foreground hover:underline"
          title={episode.name}
        >
          {episode.name}
        </Link>

        <p className="line-clamp-1 text-xs text-muted-foreground">
          {episode.episode_profile?.name ?? 'Unknown profile'}
        </p>

        {createdLabel && (
          <p className="mt-auto flex items-center gap-1 text-[11px] text-muted-foreground">
            <Clock className="h-3 w-3" />
            {createdLabel}
          </p>
        )}
      </div>

      {/* Delete action — appears on hover */}
      <div className="absolute top-2.5 left-2.5 opacity-0 transition-opacity group-hover:opacity-100">
        <AlertDialog>
          <AlertDialogTrigger asChild>
            <Button
              variant="secondary"
              size="icon"
              className="h-7 w-7 rounded-full bg-background/80 backdrop-blur-sm text-destructive hover:bg-destructive hover:text-destructive-foreground"
              onClick={(e) => e.stopPropagation()}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Delete episode?</AlertDialogTitle>
              <AlertDialogDescription>
                This will remove &ldquo;{episode.name}&rdquo; and its audio file permanently.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Cancel</AlertDialogCancel>
              <AlertDialogAction onClick={handleDelete} disabled={deleting}>
                {deleting ? 'Deleting…' : 'Delete'}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>
    </div>
  )
}
