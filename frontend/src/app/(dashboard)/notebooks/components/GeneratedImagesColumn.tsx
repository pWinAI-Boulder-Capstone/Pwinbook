'use client'

import { useMemo } from 'react'
import { useQueries } from '@tanstack/react-query'
import { formatDistanceToNow } from 'date-fns'
import { Download, Image as ImageIcon } from 'lucide-react'
import { NoteResponse } from '@/lib/types/api'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { EmptyState } from '@/components/common/EmptyState'
import { Button } from '@/components/ui/button'
import { notesApi } from '@/lib/api/notes'
import { extractGeneratedImageDataUrl, extractGeneratedImagePrompt } from './generated-image-note'

interface GeneratedImagesColumnProps {
  notes?: NoteResponse[]
  isLoading: boolean
}

interface GeneratedImageEntry {
  id: string
  title: string
  imageDataUrl: string
  prompt: string
  updated: string
}

export function GeneratedImagesColumn({ notes, isLoading }: GeneratedImagesColumnProps) {
  const noteDetailsQueries = useQueries({
    queries: (notes || []).map((note) => ({
      queryKey: ['notes', note.id, 'detail-for-generated-image'],
      queryFn: () => notesApi.get(note.id),
      enabled: !!note.id,
      staleTime: 5 * 60 * 1000,
    })),
  })

  const detailLoading = noteDetailsQueries.some((q) => q.isLoading)

  const entries = useMemo<GeneratedImageEntry[]>(() => {
    if (!notes || notes.length === 0) return []

    const byId = new Map<string, NoteResponse>()
    noteDetailsQueries.forEach((q) => {
      if (q.data?.id) {
        byId.set(q.data.id, q.data)
      }
    })

    return notes
      .map((note) => {
        const fullNote = byId.get(note.id) || note
        const imageDataUrl = extractGeneratedImageDataUrl(fullNote.content)
        if (!imageDataUrl) return null
        return {
          id: fullNote.id,
          title: fullNote.title || 'Generated Image',
          imageDataUrl,
          prompt: extractGeneratedImagePrompt(fullNote.content),
          updated: fullNote.updated || note.updated,
        }
      })
      .filter((entry): entry is GeneratedImageEntry => entry !== null)
      .sort((a, b) => new Date(b.updated).getTime() - new Date(a.updated).getTime())
  }, [notes, noteDetailsQueries])

  const handleDownload = (imageDataUrl: string, id: string) => {
    const now = new Date()
    const ts = now.toISOString().replace(/[:.]/g, '-')
    const filename = `generated-image-${id.replace(/[:]/g, '-')}-${ts}.png`
    const link = document.createElement('a')
    link.href = imageDataUrl
    link.download = filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  if (isLoading || detailLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <LoadingSpinner />
      </div>
    )
  }

  if (entries.length === 0) {
    return (
      <EmptyState
        icon={ImageIcon}
        title="No generated images yet"
        description="Generate a summary image to see it here."
      />
    )
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
      {entries.map((entry) => (
        <div key={entry.id} className="p-3 border rounded-lg space-y-2">
          <div className="flex items-start justify-between gap-2">
            <div>
              <h4 className="text-sm font-medium">{entry.title}</h4>
              <p className="text-xs text-muted-foreground">
                {formatDistanceToNow(new Date(entry.updated), { addSuffix: true })}
              </p>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => handleDownload(entry.imageDataUrl, entry.id)}
            >
              <Download className="h-3.5 w-3.5 mr-1.5" />
              Download
            </Button>
          </div>

          <div className="rounded-md border overflow-hidden bg-muted/20">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={entry.imageDataUrl}
              alt={entry.title}
              className="w-full h-44 object-cover"
            />
          </div>

          {entry.prompt && (
            <p className="text-xs text-muted-foreground line-clamp-2">{entry.prompt}</p>
          )}
        </div>
      ))}
    </div>
  )
}
