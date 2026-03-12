'use client'

import { useState, useEffect, useRef } from 'react'
import { useRouter, useParams } from 'next/navigation'

import { AppShell } from '@/components/layout/AppShell'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { EmptyState } from '@/components/common/EmptyState'
import { useToast } from '@/lib/hooks/use-toast'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Input } from '@/components/ui/input'

import {
  useFlashcardDeck,
  useFlashcardCards,
  useDeleteFlashcardDeck,
  useCreateFlashcard,
  useGenerateFlashcards,
} from '@/lib/hooks/use-flashcards'
import { useNotebooks } from '@/lib/hooks/use-notebooks'

import {
  Brain,
  Plus,
  Trash2,
  ArrowLeft,
  Play,
  Sparkles,
  BookOpen,
  Clock,
  CheckCircle,
} from 'lucide-react'

export default function FlashcardDeckDetailPage() {
  const router = useRouter()
  const params = useParams<{ deckId: string }>()
  const { toast } = useToast()

  const deckId = params.deckId
  const [isGenerating, setIsGenerating] = useState(false)

  // Poll deck every 3s while generation is running
  const { deck, isLoading: deckLoading, refetch: refetchDeck } = useFlashcardDeck(deckId, {
    refetchInterval: isGenerating ? 3000 : false,
  })
  const { cards, isLoading: cardsLoading, refetch: refetchCards } = useFlashcardCards(deckId)
  const deleteDeck = useDeleteFlashcardDeck()
  const createCard = useCreateFlashcard()
  const generateCards = useGenerateFlashcards()
  const { data: notebooks } = useNotebooks(false)
  const prevJobStatus = useRef<string | null>(null)

  const [addCardDialogOpen, setAddCardDialogOpen] = useState(false)
  const [generateDialogOpen, setGenerateDialogOpen] = useState(false)

  // Track generation status from deck's job_status_override
  useEffect(() => {
    const jobStatus = deck?.job_status_override
    if (jobStatus === 'running') {
      setIsGenerating(true)
    } else if (prevJobStatus.current === 'running' && jobStatus !== 'running') {
      // Generation just finished — refresh cards and stop polling
      setIsGenerating(false)
      setGenerateDialogOpen(false)
      refetchCards()
      refetchDeck()
      if (jobStatus === 'completed') {
        toast({
          title: 'Flashcards generated',
          description: 'Your AI-generated flashcards are ready.',
        })
      }
    }
    prevJobStatus.current = jobStatus ?? null
  }, [deck?.job_status_override]) // eslint-disable-line react-hooks/exhaustive-deps

  // Form state for adding card
  const [newQuestion, setNewQuestion] = useState('')
  const [newAnswer, setNewAnswer] = useState('')
  const [newHints, setNewHints] = useState('')
  const [newDifficulty, setNewDifficulty] = useState<'easy' | 'medium' | 'hard'>('medium')

  // Form state for generating cards
  const [selectedNotebookId, setSelectedNotebookId] = useState('')
  const [numCards, setNumCards] = useState(10)

  const handleAddCard = () => {
    if (!newQuestion.trim() || !newAnswer.trim()) {
      toast({
        title: 'Missing fields',
        description: 'Please fill in both question and answer.',
        variant: 'destructive',
      })
      return
    }

    createCard.mutate(
      {
        deck_id: deckId,
        question: newQuestion,
        answer: newAnswer,
        hints: newHints.split('\n').filter((h) => h.trim()),
        difficulty: newDifficulty,
      },
      {
        onSuccess: () => {
          setNewQuestion('')
          setNewAnswer('')
          setNewHints('')
          setNewDifficulty('medium')
          setAddCardDialogOpen(false)
          refetchCards()
          refetchDeck()
        },
      }
    )
  }

  const handleGenerateCards = () => {
    if (!selectedNotebookId) {
      toast({
        title: 'Select notebook',
        description: 'Please select a notebook to generate cards from.',
        variant: 'destructive',
      })
      return
    }

    generateCards.mutate(
      {
        deckId,
        payload: {
          notebook_id: selectedNotebookId,
          num_cards: numCards,
        },
      },
      {
        onSuccess: () => {
          setSelectedNotebookId('')
          setNumCards(10)
          setIsGenerating(true)
          setGenerateDialogOpen(false)
        },
      }
    )
  }

  const handleDeleteDeck = () => {
    deleteDeck.mutate(deckId, {
      onSuccess: () => {
        router.push('/flashcards')
      },
    })
  }

  const handleDeleteCard = (cardId: string) => {
    // TODO: Implement delete card API
    toast({
      title: 'Not implemented',
      description: `Card deletion for card ${cardId} will be available soon.`,
    })
  }

  const getProgressPercentage = (): number => {
    if (!deck || !deck.card_count || deck.card_count === 0) return 0
    return Math.round(((deck.cards_learned || 0) / deck.card_count) * 100)
  }

  const getDifficultyColor = (difficulty?: string) => {
    switch (difficulty) {
      case 'easy':
        return 'bg-green-500'
      case 'medium':
        return 'bg-yellow-500'
      case 'hard':
        return 'bg-red-500'
      default:
        return 'bg-gray-500'
    }
  }

  if (deckLoading) {
    return (
      <AppShell>
        <div className="flex items-center justify-center h-full">
          <p className="text-muted-foreground">Loading deck...</p>
        </div>
      </AppShell>
    )
  }

  if (!deck) {
    return (
      <AppShell>
        <EmptyState
          icon={Brain}
          title="Deck not found"
          description="This deck doesn't exist or has been deleted."
          action={
            <Button onClick={() => router.push('/flashcards')}>
              Back to Flashcards
            </Button>
          }
        />
      </AppShell>
    )
  }

  const progress = getProgressPercentage()

  return (
    <AppShell>
      <div className="container mx-auto p-6 space-y-6">
        {/* Header */}
        <div className="flex items-start justify-between">
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Button variant="ghost" size="sm" onClick={() => router.push('/flashcards')}>
                <ArrowLeft className="w-4 h-4 mr-2" />
                Back
              </Button>
            </div>
            <h1 className="text-3xl font-bold">{deck.name}</h1>
            {deck.description && (
              <p className="text-muted-foreground">{deck.description}</p>
            )}
            <div className="flex items-center gap-4 text-sm">
              {deck.auto_generated && (
                <Badge variant="secondary" className="flex items-center gap-1">
                  <Sparkles className="w-3 h-3" />
                  AI-generated
                </Badge>
              )}
              {deck.notebook_id && (
                <Badge variant="outline" className="flex items-center gap-1">
                  <BookOpen className="w-3 h-3" />
                  From notebook
                </Badge>
              )}
            </div>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={handleDeleteDeck}>
              <Trash2 className="w-4 h-4 mr-2" />
              Delete Deck
            </Button>
            <Button onClick={() => router.push(`/flashcards/study/${deckId}`)}>
              <Play className="w-4 h-4 mr-2" />
              Study Now
            </Button>
          </div>
        </div>

        {/* Stats Cards */}
        <div className="grid gap-4 md:grid-cols-4">
          <Card>
            <CardContent className="pt-6">
              <div className="flex items-center gap-4">
                <div className="p-3 bg-blue-500/10 rounded-full">
                  <BookOpen className="w-6 h-6 text-blue-500" />
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Total Cards</p>
                  <p className="text-2xl font-bold">{deck.card_count || 0}</p>
                </div>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-6">
              <div className="flex items-center gap-4">
                <div className="p-3 bg-green-500/10 rounded-full">
                  <CheckCircle className="w-6 h-6 text-green-500" />
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Learned</p>
                  <p className="text-2xl font-bold">{deck.cards_learned || 0}</p>
                </div>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-6">
              <div className="flex items-center gap-4">
                <div className="p-3 bg-orange-500/10 rounded-full">
                  <Clock className="w-6 h-6 text-orange-500" />
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Due</p>
                  <p className="text-2xl font-bold">{deck.cards_due || 0}</p>
                </div>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-6">
              <div className="flex items-center gap-4">
                <div className="p-3 bg-purple-500/10 rounded-full">
                  <Brain className="w-6 h-6 text-purple-500" />
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Progress</p>
                  <p className="text-2xl font-bold">{progress}%</p>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Progress Bar */}
        <Card>
          <CardHeader>
            <CardTitle>Learning Progress</CardTitle>
            <CardDescription>Your mastery of this deck</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Overall Progress</span>
                <span className="font-medium">{progress}%</span>
              </div>
              <Progress value={progress} className="h-3" />
              <div className="flex justify-between text-xs text-muted-foreground pt-2">
                <span>New: {deck.cards_new || 0}</span>
                <span>Learning: {deck.card_count ? (deck.card_count - (deck.cards_learned || 0) - (deck.cards_new || 0)) : 0}</span>
                <span>Mastered: {deck.cards_learned || 0}</span>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Action Buttons */}
        <div className="flex gap-2">
          <Dialog open={addCardDialogOpen} onOpenChange={setAddCardDialogOpen}>
            <DialogTrigger asChild>
              <Button>
                <Plus className="w-4 h-4 mr-2" />
                Add Card
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Add Flashcard</DialogTitle>
              </DialogHeader>
              <div className="space-y-4 py-4">
                <div className="space-y-2">
                  <Label htmlFor="question">Question</Label>
                  <Textarea
                    id="question"
                    placeholder="Enter your question"
                    value={newQuestion}
                    onChange={(e) => setNewQuestion(e.target.value)}
                    rows={3}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="answer">Answer</Label>
                  <Textarea
                    id="answer"
                    placeholder="Enter the answer"
                    value={newAnswer}
                    onChange={(e) => setNewAnswer(e.target.value)}
                    rows={3}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="hints">Hints (one per line)</Label>
                  <Textarea
                    id="hints"
                    placeholder="Enter hints (optional)"
                    value={newHints}
                    onChange={(e) => setNewHints(e.target.value)}
                    rows={2}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="difficulty">Difficulty</Label>
                  <select
                    id="difficulty"
                    className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    value={newDifficulty}
                    onChange={(e) => setNewDifficulty(e.target.value as 'easy' | 'medium' | 'hard')}
                  >
                    <option value="easy">Easy</option>
                    <option value="medium">Medium</option>
                    <option value="hard">Hard</option>
                  </select>
                </div>
                <div className="flex justify-end gap-2">
                  <Button variant="outline" onClick={() => setAddCardDialogOpen(false)}>
                    Cancel
                  </Button>
                  <Button onClick={handleAddCard}>
                    Add Card
                  </Button>
                </div>
              </div>
            </DialogContent>
          </Dialog>

          <Dialog open={generateDialogOpen} onOpenChange={setGenerateDialogOpen}>
            <DialogTrigger asChild>
              <Button variant="outline">
                <Sparkles className="w-4 h-4 mr-2" />
                Generate with AI
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Generate Flashcards with AI</DialogTitle>
                <CardDescription>
                  Automatically create flashcards from your notebook content
                </CardDescription>
              </DialogHeader>
              <div className="space-y-4 py-4">
                <div className="space-y-2">
                  <Label htmlFor="notebook">Select Notebook</Label>
                  <select
                    id="notebook"
                    className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    value={selectedNotebookId}
                    onChange={(e) => setSelectedNotebookId(e.target.value)}
                  >
                    <option value="">Select a notebook...</option>
                    {notebooks?.map((nb) => (
                      <option key={nb.id} value={nb.id}>
                        {nb.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="num-cards">Number of Cards</Label>
                  <Input
                    id="num-cards"
                    type="number"
                    min="1"
                    max="50"
                    value={numCards}
                    onChange={(e) => setNumCards(parseInt(e.target.value) || 10)}
                  />
                </div>
                <div className="flex justify-end gap-2">
                  <Button variant="outline" onClick={() => setGenerateDialogOpen(false)}>
                    Cancel
                  </Button>
                  <Button onClick={handleGenerateCards} disabled={generateCards.isPending}>
                    <Sparkles className="w-4 h-4 mr-2" />
                    Generate
                  </Button>
                </div>
              </div>
            </DialogContent>
          </Dialog>
        </div>

        {/* Cards List */}
        <Card>
          <CardHeader>
            <div className="flex justify-between items-center">
              <div>
                <CardTitle>Flashcards ({cards.length})</CardTitle>
                <CardDescription>Manage your flashcard content</CardDescription>
              </div>
              {isGenerating && (
                <Badge variant="secondary" className="animate-pulse">
                  <Sparkles className="w-3 h-3 mr-1" />
                  Generating...
                </Badge>
              )}
            </div>
          </CardHeader>
          <CardContent>
            {cardsLoading || isGenerating ? (
              <div className="flex flex-col items-center justify-center py-8 text-muted-foreground space-y-2">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
                <p>Generating flashcards...</p>
              </div>
            ) : cards.length === 0 ? (
              <EmptyState
                icon={Brain}
                title="No cards yet"
                description="Add cards manually or generate them with AI from your notebook content."
                action={
                  <div className="flex gap-2">
                    <Button onClick={() => setAddCardDialogOpen(true)}>
                      <Plus className="w-4 h-4 mr-2" />
                      Add Card
                    </Button>
                    <Button variant="outline" onClick={() => setGenerateDialogOpen(true)}>
                      <Sparkles className="w-4 h-4 mr-2" />
                      Generate AI
                    </Button>
                  </div>
                }
              />
            ) : (
              <div className="space-y-2">
                {cards.map((card, index) => (
                  <div
                    key={card.id}
                    className="p-4 border rounded-lg hover:bg-muted/50 transition-colors"
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex-1 space-y-2">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-muted-foreground">
                            #{index + 1}
                          </span>
                          {card.difficulty && (
                            <Badge variant="outline" className="text-xs">
                              <span className={`w-2 h-2 rounded-full mr-1 ${getDifficultyColor(card.difficulty)}`} />
                              {card.difficulty}
                            </Badge>
                          )}
                          {card.card_type && (
                            <Badge variant="secondary" className="text-xs capitalize">
                              {card.card_type}
                            </Badge>
                          )}
                        </div>
                        <p className="font-medium">{card.question}</p>
                        <div className="text-sm text-muted-foreground">
                          <span className="font-medium">Answer:</span> {card.answer}
                        </div>
                        {card.hints && card.hints.length > 0 && (
                          <div className="text-xs text-muted-foreground">
                            <span className="font-medium">Hints:</span> {card.hints.join(', ')}
                          </div>
                        )}
                        {card.mastery !== undefined && card.mastery > 0 && (
                          <div className="flex items-center gap-2">
                            <Progress value={card.mastery} className="h-1 w-32" />
                            <span className="text-xs text-muted-foreground">{card.mastery}%</span>
                          </div>
                        )}
                      </div>
                      <div className="flex gap-1">
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => handleDeleteCard(card.id)}
                        >
                          <Trash2 className="w-4 h-4" />
                        </Button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </AppShell>
  )
}
