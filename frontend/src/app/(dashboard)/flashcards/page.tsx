'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'

import { AppShell } from '@/components/layout/AppShell'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { Progress } from '@/components/ui/progress'
import { EmptyState } from '@/components/common/EmptyState'
import { useToast } from '@/lib/hooks/use-toast'

import { useFlashcardDecks, useDeleteFlashcardDeck, useCreateFlashcardDeck } from '@/lib/hooks/use-flashcards'
import { useNotebooks } from '@/lib/hooks/use-notebooks'

import type { FlashcardDeck } from '@/lib/types/flashcards'

import { Brain, Plus, Trash2, Edit, Play, BookOpen, Flame, Award, Clock, ChevronRight, Sparkles } from 'lucide-react'

export default function FlashcardsPage() {
  const router = useRouter()
  const { toast } = useToast()

  const { decks, isLoading, refetch } = useFlashcardDecks()
  const { data: notebooks } = useNotebooks(false)
  const deleteDeck = useDeleteFlashcardDeck()
  const createDeck = useCreateFlashcardDeck()

  const [createDialogOpen, setCreateDialogOpen] = useState(false)
  const [selectedDeck, setSelectedDeck] = useState<FlashcardDeck | null>(null)

  // Form state for creating deck
  const [newDeckName, setNewDeckName] = useState('')
  const [newDeckDescription, setNewDeckDescription] = useState('')
  const [selectedNotebookId, setSelectedNotebookId] = useState('')

  const handleCreateDeck = () => {
    if (!newDeckName.trim()) {
      toast({
        title: 'Name required',
        description: 'Please enter a name for your deck.',
        variant: 'destructive',
      })
      return
    }

    createDeck.mutate(
      {
        name: newDeckName,
        description: newDeckDescription || undefined,
        notebook_id: selectedNotebookId || undefined,
      },
      {
        onSuccess: () => {
          setNewDeckName('')
          setNewDeckDescription('')
          setSelectedNotebookId('')
          setCreateDialogOpen(false)
          refetch()
        },
      }
    )
  }

  const handleDeleteDeck = (deckId: string) => {
    deleteDeck.mutate(deckId, {
      onSuccess: () => {
        if (selectedDeck?.id === deckId) {
          setSelectedDeck(null)
        }
        refetch()
      },
    })
  }

  const handleStartStudy = (deck: FlashcardDeck) => {
    router.push(`/flashcards/study/${deck.id}`)
  }

  // Calculate progress percentage for a deck
  const getProgressPercentage = (deck: FlashcardDeck): number => {
    if (!deck.card_count || deck.card_count === 0) return 0
    return Math.round(((deck.cards_learned || 0) / deck.card_count) * 100)
  }

  // Get status badge based on deck state
  const getDeckStatus = (deck: FlashcardDeck) => {
    if (!deck.card_count || deck.card_count === 0) {
      return { label: 'Empty', variant: 'secondary' as const }
    }
    const progress = getProgressPercentage(deck)
    if (progress >= 80) {
      return { label: 'Mastered', variant: 'default' as const }
    }
    if (deck.cards_due && deck.cards_due > 0) {
      return { label: `${deck.cards_due} due`, variant: 'destructive' as const }
    }
    if (deck.cards_new && deck.cards_new > 0) {
      return { label: `${deck.cards_new} new`, variant: 'secondary' as const }
    }
    return { label: 'Review', variant: 'outline' as const }
  }

  if (isLoading) {
    return (
      <AppShell>
        <div className="flex items-center justify-center h-full">
          <div className="text-center space-y-4">
            <Brain className="w-12 h-12 mx-auto text-muted-foreground animate-pulse" />
            <p className="text-muted-foreground">Loading flashcards...</p>
          </div>
        </div>
      </AppShell>
    )
  }

  return (
    <AppShell>
      <div className="container mx-auto p-6 space-y-6">
        {/* Header with gradient background */}
        <div className="relative overflow-hidden rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 p-6 text-white animate-in fade-in slide-in-from-top-4 duration-500">
          <div className="relative z-10 flex justify-between items-center">
            <div className="space-y-2">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-white/10 rounded-lg">
                  <Brain className="w-8 h-8" />
                </div>
                <div>
                  <h1 className="text-2xl font-bold">Flashcards</h1>
                  <p className="text-white/80 text-sm">Study and test your knowledge from notebook content</p>
                </div>
              </div>
            </div>
            <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
              <DialogTrigger asChild>
                <Button size="lg" className="bg-white text-blue-600 hover:bg-white/90">
                  <Plus className="w-5 h-5 mr-2" />
                  Create Deck
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Create Flashcard Deck</DialogTitle>
                </DialogHeader>
                <div className="space-y-4 py-4">
                  <div className="space-y-2">
                    <Label htmlFor="deck-name">Deck Name</Label>
                    <Input
                      id="deck-name"
                      placeholder="e.g., Machine Learning Basics"
                      value={newDeckName}
                      onChange={(e) => setNewDeckName(e.target.value)}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="deck-description">Description (optional)</Label>
                    <Textarea
                      id="deck-description"
                      placeholder="Brief description of what this deck covers"
                      value={newDeckDescription}
                      onChange={(e) => setNewDeckDescription(e.target.value)}
                      rows={3}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="notebook">Source Notebook (optional)</Label>
                    <select
                      id="notebook"
                      className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                      value={selectedNotebookId}
                      onChange={(e) => setSelectedNotebookId(e.target.value)}
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
                    <Button variant="outline" onClick={() => setCreateDialogOpen(false)}>
                      Cancel
                    </Button>
                    <Button onClick={handleCreateDeck}>
                      Create Deck
                    </Button>
                  </div>
                </div>
              </DialogContent>
            </Dialog>
          </div>
          {/* Decorative background elements */}
          <div className="absolute top-0 right-0 w-64 h-64 bg-white/5 rounded-full -translate-y-1/2 translate-x-1/2" />
          <div className="absolute bottom-0 left-0 w-32 h-32 bg-white/5 rounded-full translate-y-1/2 -translate-x-1/2" />
        </div>

        {/* Stats Overview */}
        {decks.length > 0 && (
          <div className="grid gap-4 md:grid-cols-4 animate-in fade-in slide-in-from-bottom-4 duration-500">
            <Card className="border-l-4 border-l-blue-500">
              <CardContent className="pt-6">
                <div className="flex items-center gap-4">
                  <div className="p-3 bg-blue-500/10 rounded-full">
                    <BookOpen className="w-6 h-6 text-blue-500" />
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">Total Decks</p>
                    <p className="text-2xl font-bold">{decks.length}</p>
                  </div>
                </div>
              </CardContent>
            </Card>
            <Card className="border-l-4 border-l-green-500">
              <CardContent className="pt-6">
                <div className="flex items-center gap-4">
                  <div className="p-3 bg-green-500/10 rounded-full">
                    <Award className="w-6 h-6 text-green-500" />
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">Cards Learned</p>
                    <p className="text-2xl font-bold">
                      {decks.reduce((acc, d) => acc + (d.cards_learned || 0), 0)}
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>
            <Card className="border-l-4 border-l-orange-500">
              <CardContent className="pt-6">
                <div className="flex items-center gap-4">
                  <div className="p-3 bg-orange-500/10 rounded-full">
                    <Clock className="w-6 h-6 text-orange-500" />
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">Cards Due</p>
                    <p className="text-2xl font-bold">
                      {decks.reduce((acc, d) => acc + (d.cards_due || 0), 0)}
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>
            <Card className="border-l-4 border-l-red-500">
              <CardContent className="pt-6">
                <div className="flex items-center gap-4">
                  <div className="p-3 bg-red-500/10 rounded-full">
                    <Flame className="w-6 h-6 text-red-500" />
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">New Cards</p>
                    <p className="text-2xl font-bold">
                      {decks.reduce((acc, d) => acc + (d.cards_new || 0), 0)}
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
        )}

        {/* Main content */}
        {decks.length === 0 ? (
          <div className="animate-in fade-in zoom-in-95 duration-300">
              <EmptyState
                icon={Brain}
                title="No flashcard decks yet"
                description="Create your first deck to start studying. You can generate cards from notebook content or create them manually."
                action={
                  <Button onClick={() => setCreateDialogOpen(true)} size="lg">
                    <Plus className="w-5 h-5 mr-2" />
                    Create Deck
                  </Button>
                }
              />
            </div>
          ) : (
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 animate-in fade-in duration-500">
              {decks.map((deck, index) => {
                const progress = getProgressPercentage(deck)
                const status = getDeckStatus(deck)

                return (
                  <div
                    key={deck.id}
                    className="animate-in fade-in slide-in-from-bottom-4"
                    style={{ animationDelay: `${index * 50}ms` }}
                  >
                    <Card className="group hover:shadow-lg transition-all duration-300 hover:-translate-y-1 border-2 hover:border-blue-500/50">
                      <CardHeader className="space-y-1 pb-3">
                        <div className="flex justify-between items-start">
                          <div className="space-y-1 flex-1">
                            <CardTitle className="text-lg group-hover:text-blue-500 transition-colors">
                              {deck.name}
                            </CardTitle>
                            {deck.description && (
                              <CardDescription className="line-clamp-2">
                                {deck.description}
                              </CardDescription>
                            )}
                          </div>
                          <Badge
                            variant={status.variant}
                            className="ml-2 flex items-center gap-1"
                          >
                            {status.variant === 'destructive' && <Clock className="w-3 h-3" />}
                            {status.label}
                          </Badge>
                        </div>
                      </CardHeader>
                      <CardContent className="space-y-4">
                        {/* Progress bar */}
                        <div className="space-y-2">
                          <div className="flex justify-between text-xs">
                            <span className="text-muted-foreground">Progress</span>
                            <span className="font-medium">{progress}%</span>
                          </div>
                          <Progress value={progress} className="h-2" />
                        </div>

                        {/* Stats grid */}
                        <div className="grid grid-cols-3 gap-2 text-center">
                          <div className="p-2 bg-blue-500/10 rounded-lg">
                            <p className="text-xs text-muted-foreground">Total</p>
                            <p className="text-lg font-semibold text-blue-500">{deck.card_count || 0}</p>
                          </div>
                          <div className="p-2 bg-green-500/10 rounded-lg">
                            <p className="text-xs text-muted-foreground">Learned</p>
                            <p className="text-lg font-semibold text-green-500">{deck.cards_learned || 0}</p>
                          </div>
                          <div className="p-2 bg-orange-500/10 rounded-lg">
                            <p className="text-xs text-muted-foreground">Due</p>
                            <p className="text-lg font-semibold text-orange-500">{deck.cards_due || 0}</p>
                          </div>
                        </div>

                        <Separator />

                        {/* Action buttons */}
                        <div className="flex gap-2">
                          <Button
                            size="sm"
                            className="flex-1 bg-gradient-to-r from-blue-500 to-indigo-500 hover:from-blue-600 hover:to-indigo-600"
                            onClick={() => handleStartStudy(deck)}
                          >
                            <Play className="w-4 h-4 mr-2" />
                            Study
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => router.push(`/flashcards/decks/${deck.id}`)}
                            className="px-3"
                          >
                            <Edit className="w-4 h-4" />
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => router.push(`/flashcards/decks/${deck.id}`)}
                            className="px-3"
                          >
                            <ChevronRight className="w-4 h-4" />
                          </Button>
                          <Button
                            size="sm"
                            variant="destructive"
                            onClick={() => handleDeleteDeck(deck.id)}
                            className="px-3"
                          >
                            <Trash2 className="w-4 h-4" />
                          </Button>
                        </div>

                        {/* Auto-generated badge */}
                        {deck.auto_generated && (
                          <div className="flex items-center gap-1 text-xs text-muted-foreground">
                            <Sparkles className="w-3 h-3" />
                            AI-generated from notebook
                          </div>
                        )}
                      </CardContent>
                    </Card>
                  </div>
                )
              })}
            </div>
          )}
      </div>
    </AppShell>
  )
}
