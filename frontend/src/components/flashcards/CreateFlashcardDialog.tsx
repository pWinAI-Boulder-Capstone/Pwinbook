'use client'

import * as React from 'react'
import { useRouter } from 'next/navigation'

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { useCreateFlashcardDeck } from '@/lib/hooks/use-flashcards'
import { useNotebooks } from '@/lib/hooks/use-notebooks'

interface CreateFlashcardDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function CreateFlashcardDialog({ open, onOpenChange }: CreateFlashcardDialogProps) {
  const router = useRouter()
  const createDeck = useCreateFlashcardDeck()
  const { data: notebooks } = useNotebooks(false)

  const [name, setName] = React.useState('')
  const [description, setDescription] = React.useState('')
  const [notebookId, setNotebookId] = React.useState('')

  const handleSubmit = () => {
    if (!name.trim()) {
      return
    }

    createDeck.mutate(
      {
        name,
        description: description || undefined,
        notebook_id: notebookId || undefined,
      },
      {
        onSuccess: () => {
          setName('')
          setDescription('')
          setNotebookId('')
          onOpenChange(false)
          router.push('/flashcards')
        },
      }
    )
  }

  React.useEffect(() => {
    if (!open) {
      setName('')
      setDescription('')
      setNotebookId('')
    }
  }, [open])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Create Flashcard Deck</DialogTitle>
          <DialogDescription>
            Create a new deck to study. You can generate cards from notebook content later.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label htmlFor="flashcard-name">Deck Name</Label>
            <Input
              id="flashcard-name"
              placeholder="e.g., Machine Learning Basics"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="flashcard-description">Description (optional)</Label>
            <Textarea
              id="flashcard-description"
              placeholder="Brief description of what this deck covers"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="flashcard-notebook">Source Notebook (optional)</Label>
            <select
              id="flashcard-notebook"
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              value={notebookId}
              onChange={(e) => setNotebookId(e.target.value)}
            >
              <option value="">No notebook</option>
              {notebooks?.map((nb) => (
                <option key={nb.id} value={nb.id}>
                  {nb.name}
                </option>
              ))}
            </select>
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button onClick={handleSubmit} disabled={!name.trim()}>
              Create Deck
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
