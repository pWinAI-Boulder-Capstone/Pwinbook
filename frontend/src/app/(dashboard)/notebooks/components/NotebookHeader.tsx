'use client'

import { useState } from 'react'
import { NotebookResponse } from '@/lib/types/api'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Archive, ArchiveRestore, Image as ImageIcon, Sparkles, Trash2 } from 'lucide-react'
import { useQuickSummary, useQuickSummaryImage, useUpdateNotebook, useDeleteNotebook } from '@/lib/hooks/use-notebooks'
import { useCreateNote } from '@/lib/hooks/use-notes'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { formatDistanceToNow } from 'date-fns'
import { InlineEdit } from '@/components/common/InlineEdit'
import { QuickSummaryImageDialog } from './QuickSummaryImageDialog'
import { buildGeneratedImageNoteContent } from './generated-image-note'

interface NotebookHeaderProps {
  notebook: NotebookResponse
  onQuickSummaryCreated?: (noteId: string) => void
}

export function NotebookHeader({ notebook, onQuickSummaryCreated }: NotebookHeaderProps) {
  const [showDeleteDialog, setShowDeleteDialog] = useState(false)
  const [summaryImageOpen, setSummaryImageOpen] = useState(false)
  const [summaryImageDataUrl, setSummaryImageDataUrl] = useState<string | null>(null)
  const [summaryImagePrompt, setSummaryImagePrompt] = useState('')
  const [summaryNoteId, setSummaryNoteId] = useState<string | undefined>(undefined)
  
  const updateNotebook = useUpdateNotebook()
  const deleteNotebook = useDeleteNotebook()
  const quickSummary = useQuickSummary()
  const quickSummaryImage = useQuickSummaryImage()
  const createNote = useCreateNote()

  const handleUpdateName = async (name: string) => {
    if (!name || name === notebook.name) return
    
    await updateNotebook.mutateAsync({
      id: notebook.id,
      data: { name }
    })
  }

  const handleUpdateDescription = async (description: string) => {
    if (description === notebook.description) return
    
    await updateNotebook.mutateAsync({
      id: notebook.id,
      data: { description: description || undefined }
    })
  }

  const handleArchiveToggle = () => {
    updateNotebook.mutate({
      id: notebook.id,
      data: { archived: !notebook.archived }
    })
  }

  const handleDelete = () => {
    deleteNotebook.mutate(notebook.id)
    setShowDeleteDialog(false)
  }

  const handleQuickSummary = async () => {
    const result = await quickSummary.mutateAsync({
      id: notebook.id,
      data: {
        title: `Quick Summary - ${notebook.name}`,
        include_notes: true,
        include_insights: true,
      }
    })
    if (result?.note?.id) {
      setSummaryNoteId(result.note.id)
      onQuickSummaryCreated?.(result.note.id)
    }
  }

  const handleGenerateSummaryImage = async () => {
    setSummaryImageOpen(true)
    try {
      const result = await quickSummaryImage.mutateAsync({
        id: notebook.id,
        data: {
          note_id: summaryNoteId,
        },
      })
      setSummaryImageDataUrl(result.image_data_url)
      setSummaryImagePrompt(result.prompt)
      if (result.note?.id) {
        setSummaryNoteId(result.note.id)
      }
      await createNote.mutateAsync({
        notebook_id: notebook.id,
        note_type: 'ai',
        title: `Generated Image - ${notebook.name}`,
        content: buildGeneratedImageNoteContent(
          result.image_data_url,
          result.prompt,
          result.note?.id
        ),
      })
    } catch {
      // Error toast is handled by the mutation.
    }
  }

  return (
    <>
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3 flex-1">
            <InlineEdit
              value={notebook.name}
              onSave={handleUpdateName}
              className="text-xl font-semibold"
              inputClassName="text-xl font-semibold"
              placeholder="Notebook name"
              />
              {notebook.archived && (
                <Badge variant="secondary">Archived</Badge>
              )}
            </div>
            <div className="flex gap-1.5">
              <Button
                variant="outline"
                size="sm"
                onClick={handleQuickSummary}
                disabled={quickSummary.isPending}
                className="h-8"
              >
                <Sparkles className="h-3.5 w-3.5 mr-1.5" />
                {quickSummary.isPending ? 'Summarizing…' : 'Summary'}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={handleGenerateSummaryImage}
                disabled={quickSummary.isPending || quickSummaryImage.isPending}
                className="h-8"
              >
                <ImageIcon className="h-3.5 w-3.5 mr-1.5" />
                {quickSummaryImage.isPending ? 'Generating…' : 'Summary Image'}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={handleArchiveToggle}
                className="h-8"
              >
                {notebook.archived ? (
                  <ArchiveRestore className="h-3.5 w-3.5" />
                ) : (
                  <Archive className="h-3.5 w-3.5" />
                )}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setShowDeleteDialog(true)}
                className="h-8 text-destructive hover:text-destructive"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
        
        <InlineEdit
          value={notebook.description || ''}
          onSave={handleUpdateDescription}
          className="text-sm text-muted-foreground"
          inputClassName="text-sm text-muted-foreground"
          placeholder="Add a description..."
          multiline
          emptyText="Add a description..."
        />
        
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span>Updated {formatDistanceToNow(new Date(notebook.updated), { addSuffix: true })}</span>
        </div>
      </div>

      <ConfirmDialog
        open={showDeleteDialog}
        onOpenChange={setShowDeleteDialog}
        title="Delete Notebook"
        description={`Are you sure you want to delete "${notebook.name}"? This action cannot be undone and will delete all sources, notes, and chat sessions.`}
        confirmText="Delete Forever"
        confirmVariant="destructive"
        onConfirm={handleDelete}
      />

      <QuickSummaryImageDialog
        open={summaryImageOpen}
        onOpenChange={setSummaryImageOpen}
        imageDataUrl={summaryImageDataUrl}
        prompt={summaryImagePrompt}
        isGenerating={quickSummaryImage.isPending}
        onGenerate={handleGenerateSummaryImage}
      />
    </>
  )
}
