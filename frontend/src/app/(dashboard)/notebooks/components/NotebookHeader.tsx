'use client'

import { useState } from 'react'
import { NotebookResponse } from '@/lib/types/api'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Archive, ArchiveRestore, Sparkles, Trash2 } from 'lucide-react'
import { useQuickSummary, useUpdateNotebook, useDeleteNotebook } from '@/lib/hooks/use-notebooks'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { formatDistanceToNow } from 'date-fns'
import { InlineEdit } from '@/components/common/InlineEdit'

interface NotebookHeaderProps {
  notebook: NotebookResponse
  onQuickSummaryCreated?: (noteId: string) => void
}

export function NotebookHeader({ notebook, onQuickSummaryCreated }: NotebookHeaderProps) {
  const [showDeleteDialog, setShowDeleteDialog] = useState(false)
  
  const updateNotebook = useUpdateNotebook()
  const deleteNotebook = useDeleteNotebook()
  const quickSummary = useQuickSummary()

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
      onQuickSummaryCreated?.(result.note.id)
    }
  }

  return (
    <>
      <div className="border-b pb-6">
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3 flex-1">
              <InlineEdit
                value={notebook.name}
                onSave={handleUpdateName}
                className="text-2xl font-bold"
                inputClassName="text-2xl font-bold"
                placeholder="Notebook name"
              />
              {notebook.archived && (
                <Badge variant="secondary">Archived</Badge>
              )}
            </div>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={handleQuickSummary}
                disabled={quickSummary.isPending}
              >
                <Sparkles className="h-4 w-4 mr-2" />
                {quickSummary.isPending ? 'Summarizing…' : 'Quick Summary'}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={handleArchiveToggle}
              >
                {notebook.archived ? (
                  <>
                    <ArchiveRestore className="h-4 w-4 mr-2" />
                    Unarchive
                  </>
                ) : (
                  <>
                    <Archive className="h-4 w-4 mr-2" />
                    Archive
                  </>
                )}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setShowDeleteDialog(true)}
                className="text-red-600 hover:text-red-700"
              >
                <Trash2 className="h-4 w-4 mr-2" />
                Delete
              </Button>
            </div>
          </div>
          
          <InlineEdit
            value={notebook.description || ''}
            onSave={handleUpdateDescription}
            className="text-muted-foreground"
            inputClassName="text-muted-foreground"
            placeholder="Add a description..."
            multiline
            emptyText="Add a description..."
          />
          
          <div className="text-sm text-muted-foreground">
            Created {formatDistanceToNow(new Date(notebook.created), { addSuffix: true })} • 
            Updated {formatDistanceToNow(new Date(notebook.updated), { addSuffix: true })}
          </div>
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
    </>
  )
}
