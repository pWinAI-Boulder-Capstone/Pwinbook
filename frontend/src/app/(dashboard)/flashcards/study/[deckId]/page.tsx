'use client'

import { useState, useEffect, useRef } from 'react'
import { useRouter, useParams } from 'next/navigation'

import { AppShell } from '@/components/layout/AppShell'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { EmptyState } from '@/components/common/EmptyState'

import {
  useFlashcardDeck,
  useFlashcardCards,
  useCreateFlashcardSession,
  useSubmitFlashcardAnswer,
  useCompleteFlashcardSession,
} from '@/lib/hooks/use-flashcards'

import {
  Brain,
  Check,
  X,
  ArrowRight,
  RotateCcw,
  Flame,
  TrendingUp,
  BookOpen,
  ChevronLeft,
} from 'lucide-react'

export default function FlashcardStudyPage() {
  const router = useRouter()
  const params = useParams<{ deckId: string }>()

  const deckId = params.deckId
  const { deck, isLoading: deckLoading } = useFlashcardDeck(deckId)
  const { cards, isLoading: cardsLoading } = useFlashcardCards(deckId)

  const createSession = useCreateFlashcardSession()
  const submitAnswer = useSubmitFlashcardAnswer()
  const completeSession = useCompleteFlashcardSession()

  const [sessionId, setSessionId] = useState<string | null>(null)
  const [currentCardIndex, setCurrentCardIndex] = useState(0)
  const [showAnswer, setShowAnswer] = useState(false)
  const [isFlipped, setIsFlipped] = useState(false)
  const [completed, setCompleted] = useState(false)
  const [score, setScore] = useState({ correct: 0, total: 0 })
  const [studyStreak, setStudyStreak] = useState(0)
  const sessionInitRef = useRef(false)

  const currentCard = cards[currentCardIndex]

  // Initialize session on mount
  useEffect(() => {
    if (deckId && !sessionId && !sessionInitRef.current) {
      sessionInitRef.current = true
      createSession.mutate(deckId, {
        onSuccess: (data) => {
          setSessionId(data.id)
        },
      })
    }
  }, [deckId, sessionId]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleShowAnswer = () => {
    setShowAnswer(true)
  }

  const handleAnswer = (correct: boolean) => {
    if (!sessionId || !currentCard) return

    submitAnswer.mutate(
      {
        sessionId,
        payload: {
          card_id: currentCard.id,
          user_answer: showAnswer ? (correct ? 'Correct' : 'Incorrect') : '',
          correct,
        },
      },
      {
        onSuccess: () => {
          setScore((prev) => ({
            correct: prev.correct + (correct ? 1 : 0),
            total: prev.total + 1,
          }))

          if (correct) {
            setStudyStreak((prev) => prev + 1)
          } else {
            setStudyStreak(0)
          }

          if (currentCardIndex < cards.length - 1) {
            setTimeout(() => {
              setCurrentCardIndex((prev) => prev + 1)
              setShowAnswer(false)
              setIsFlipped(false)
            }, 300)
          } else {
            completeSession.mutate(sessionId, {
              onSuccess: () => {
                setCompleted(true)
              },
            })
          }
        },
      }
    )
  }

  const handleRestart = () => {
    setCompleted(false)
    setCurrentCardIndex(0)
    setShowAnswer(false)
    setIsFlipped(false)
    setScore({ correct: 0, total: 0 })
    setStudyStreak(0)
    sessionInitRef.current = false

    if (deckId) {
      createSession.mutate(deckId, {
        onSuccess: (data) => {
          setSessionId(data.id)
        },
      })
    }
  }

  const getDifficultyColor = (difficulty?: string) => {
    switch (difficulty) {
      case 'easy':
        return 'text-green-500'
      case 'medium':
        return 'text-yellow-500'
      case 'hard':
        return 'text-red-500'
      default:
        return 'text-gray-500'
    }
  }

  const getCardTypeIcon = (type?: string) => {
    switch (type) {
      case 'cloze':
        return '📝'
      case 'multiple_choice':
        return '🔘'
      default:
        return '📇'
    }
  }

  if (deckLoading || cardsLoading) {
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

  if (!deck || cards.length === 0) {
    return (
      <AppShell>
        <EmptyState
          icon={Brain}
          title="No cards to study"
          description="This deck is empty. Add some flashcards first."
          action={
            <Button onClick={() => router.push(`/flashcards/decks/${deckId}`)}>
              Go to Deck
            </Button>
          }
        />
      </AppShell>
    )
  }

  if (completed) {
    const percentage = Math.round((score.correct / score.total) * 100)
    const percentageDisplay = percentage || 100

    return (
      <AppShell>
        <div className="container mx-auto p-6 max-w-2xl">
          <Card className="border-2">
            <CardHeader className="text-center space-y-4">
              <div className="mx-auto p-4 bg-gradient-to-r from-blue-500 to-indigo-500 rounded-full w-20 h-20 flex items-center justify-center">
                <Brain className="w-10 h-10 text-white" />
              </div>
              <CardTitle className="text-2xl">Study Session Complete!</CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="grid grid-cols-3 gap-4 text-center">
                <div className="p-4 bg-blue-500/10 rounded-lg">
                  <p className="text-3xl font-bold text-blue-500">{percentageDisplay}%</p>
                  <p className="text-sm text-muted-foreground">Score</p>
                </div>
                <div className="p-4 bg-green-500/10 rounded-lg">
                  <p className="text-3xl font-bold text-green-500">{score.correct}</p>
                  <p className="text-sm text-muted-foreground">Correct</p>
                </div>
                <div className="p-4 bg-purple-500/10 rounded-lg">
                  <p className="text-3xl font-bold text-purple-500">{score.total}</p>
                  <p className="text-sm text-muted-foreground">Total</p>
                </div>
              </div>

              <div className="space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Performance</span>
                  <span className="font-medium">{percentageDisplay}%</span>
                </div>
                <Progress value={percentageDisplay} className="h-3" />
              </div>

              {percentageDisplay >= 80 && (
                <div className="p-4 bg-green-500/10 border border-green-500/20 rounded-lg">
                  <div className="flex items-center gap-2 text-green-600">
                    <Flame className="w-5 h-5" />
                    <span className="font-medium">Excellent! You&apos;ve mastered this deck!</span>
                  </div>
                </div>
              )}

              {percentageDisplay >= 60 && percentageDisplay < 80 && (
                <div className="p-4 bg-blue-500/10 border border-blue-500/20 rounded-lg">
                  <div className="flex items-center gap-2 text-blue-600">
                    <TrendingUp className="w-5 h-5" />
                    <span className="font-medium">Great progress! Keep studying!</span>
                  </div>
                </div>
              )}

              {percentageDisplay < 60 && (
                <div className="p-4 bg-orange-500/10 border border-orange-500/20 rounded-lg">
                  <div className="flex items-center gap-2 text-orange-600">
                    <BookOpen className="w-5 h-5" />
                    <span className="font-medium">Keep practicing! You&apos;ll get there!</span>
                  </div>
                </div>
              )}

              <div className="flex justify-center gap-4 pt-4">
                <Button variant="outline" onClick={() => router.push(`/flashcards/decks/${deckId}`)}>
                  Back to Deck
                </Button>
                <Button onClick={handleRestart} className="bg-gradient-to-r from-blue-500 to-indigo-500">
                  <RotateCcw className="w-4 h-4 mr-2" />
                  Study Again
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      </AppShell>
    )
  }

  const progress = ((currentCardIndex) / cards.length) * 100

  return (
    <AppShell>
      <div className="container mx-auto p-6 max-w-3xl space-y-6">
        {/* Header */}
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => router.push(`/flashcards/decks/${deckId}`)}>
              <ChevronLeft className="w-4 h-4 mr-1" />
              Back
            </Button>
            <div className="flex-1" />
            {studyStreak > 2 && (
              <Badge variant="secondary" className="flex items-center gap-1 animate-in fade-in">
                <Flame className="w-3 h-3 text-orange-500" />
                {studyStreak} streak
              </Badge>
            )}
          </div>

          <div className="flex justify-between items-center">
            <div>
              <h1 className="text-2xl font-bold">{deck.name}</h1>
              <p className="text-muted-foreground">
                Card {currentCardIndex + 1} of {cards.length}
              </p>
            </div>
            <Badge variant={score.correct > score.total - score.correct ? 'default' : 'secondary'} className="text-sm px-4 py-2">
              <Check className="w-4 h-4 mr-1" />
              {score.correct}/{score.total}
            </Badge>
          </div>
        </div>

        {/* Progress */}
        <div className="space-y-2">
          <Progress value={progress} className="h-2" />
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>{Math.round(progress)}% complete</span>
            <span>{cards.length - currentCardIndex - 1} cards remaining</span>
          </div>
        </div>

        {/* Flashcard */}
        <div className="pointer-events-none">
          <Card
            className="min-h-[400px] cursor-pointer transition-shadow duration-300 hover:shadow-xl pointer-events-auto"
            onClick={(e) => {
              if (!showAnswer) {
                e.stopPropagation()
                handleShowAnswer()
              }
            }}
          >
            <CardHeader className="space-y-4">
              <div className="flex justify-between items-start">
                {currentCard?.difficulty && (
                  <Badge variant="outline" className={getDifficultyColor(currentCard.difficulty)}>
                    {currentCard.difficulty}
                  </Badge>
                )}
                {currentCard?.card_type && (
                  <Badge variant="secondary" className="text-xs">
                    {getCardTypeIcon(currentCard.card_type)} {currentCard.card_type.replace('_', ' ')}
                  </Badge>
                )}
                {currentCard?.tags && currentCard.tags.length > 0 && (
                  <div className="flex gap-1">
                    {currentCard.tags.slice(0, 3).map((tag, idx) => (
                      <Badge key={idx} variant="outline" className="text-xs">
                        {tag}
                      </Badge>
                    ))}
                  </div>
                )}
              </div>
              <CardTitle className="text-xl mt-4">{currentCard?.question}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 flex-1 flex flex-col justify-center">
              {showAnswer ? (
                <div className="space-y-4 animate-in fade-in duration-300">
                  <div className="p-6 bg-gradient-to-br from-blue-500/10 to-indigo-500/10 rounded-xl border border-blue-500/20">
                    <p className="font-medium text-sm text-blue-600 mb-2 flex items-center gap-2">
                      <Brain className="w-4 h-4" />
                      Answer
                    </p>
                    <p className="text-lg leading-relaxed">{currentCard?.answer}</p>
                  </div>

                  {currentCard?.explanation && (
                    <div className="p-4 bg-muted/50 rounded-lg">
                      <p className="font-medium text-sm text-muted-foreground mb-1">Explanation:</p>
                      <p className="text-sm text-muted-foreground">{currentCard.explanation}</p>
                    </div>
                  )}

                  {currentCard?.hints && currentCard.hints.length > 0 && (
                    <div className="space-y-2">
                      <p className="font-medium text-sm text-muted-foreground flex items-center gap-2">
                        💡 Hints
                      </p>
                      {currentCard.hints.map((hint, idx) => (
                        <p
                          key={idx}
                          className="text-sm text-muted-foreground pl-4 border-l-2 border-yellow-500/50"
                        >
                          {hint}
                        </p>
                      ))}
                    </div>
                  )}

                  <div className="flex justify-center gap-3 pt-6">
                    <Button
                      variant="destructive"
                      size="lg"
                      className="w-32"
                      onClick={(e) => {
                        e.stopPropagation()
                        handleAnswer(false)
                      }}
                    >
                      <X className="w-5 h-5 mr-2" />
                      Incorrect
                    </Button>
                    <Button
                      variant="default"
                      size="lg"
                      className="w-32 bg-gradient-to-r from-green-500 to-emerald-500 hover:from-green-600 hover:to-emerald-600"
                      onClick={(e) => {
                        e.stopPropagation()
                        handleAnswer(true)
                      }}
                    >
                      <Check className="w-5 h-5 mr-2" />
                      Correct
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center flex-1 py-12">
                  <div className="p-6 bg-muted/30 rounded-full mb-6 animate-in fade-in">
                    <Brain className="w-16 h-16 text-muted-foreground/50" />
                  </div>
                  <p className="text-muted-foreground text-sm animate-in fade-in">
                    Click to reveal the answer
                  </p>
                  <Button
                    size="lg"
                    className="mt-4 bg-gradient-to-r from-blue-500 to-indigo-500 animate-in slide-in-from-bottom-2"
                    onClick={(e) => {
                      e.stopPropagation()
                      handleShowAnswer()
                    }}
                  >
                    Show Answer
                    <ArrowRight className="w-5 h-5 ml-2" />
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Navigation hints */}
        <div className="flex justify-between items-center text-sm text-muted-foreground">
          <p>Press Space or click to flip</p>
          <div className="flex gap-4">
            <span className="flex items-center gap-1">
              <kbd className="px-2 py-1 bg-muted rounded text-xs">1</kbd> Incorrect
            </span>
            <span className="flex items-center gap-1">
              <kbd className="px-2 py-1 bg-muted rounded text-xs">2</kbd> Correct
            </span>
          </div>
        </div>
      </div>
    </AppShell>
  )
}
