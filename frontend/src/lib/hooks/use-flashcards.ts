'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { flashcardsApi } from '@/lib/api/flashcards'
import { QUERY_KEYS } from '@/lib/api/query-client'
import { useToast } from '@/lib/hooks/use-toast'
import type {
  FlashcardDeckCreate,
  FlashcardDeckUpdate,
  FlashcardGenerateRequest,
  FlashcardCreate,
  FlashcardAnswerSubmit,
} from '@/lib/types/flashcards'

// ---------------------------------------------------------------------------
// Deck hooks
// ---------------------------------------------------------------------------

export function useFlashcardDecks(notebookId?: string) {
  const query = useQuery({
    queryKey: notebookId
      ? QUERY_KEYS.flashcardDecks
      : QUERY_KEYS.flashcardDecks,
    queryFn: () => flashcardsApi.listDecks(notebookId),
  })

  return {
    ...query,
    decks: query.data ?? [],
  }
}

export function useFlashcardDeck(deckId: string, options?: { refetchInterval?: number | false }) {
  const query = useQuery({
    queryKey: QUERY_KEYS.flashcardDeck(deckId),
    queryFn: () => flashcardsApi.getDeck(deckId),
    enabled: !!deckId,
    refetchInterval: options?.refetchInterval,
    refetchOnMount: 'always',
    refetchOnWindowFocus: true,
    staleTime: 0,
  })

  return {
    ...query,
    deck: query.data,
  }
}

export function useCreateFlashcardDeck() {
  const queryClient = useQueryClient()
  const { toast } = useToast()

  return useMutation({
    mutationFn: (payload: FlashcardDeckCreate) =>
      flashcardsApi.createDeck(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.flashcardDecks })
      toast({
        title: 'Deck created',
        description: 'Your flashcard deck has been created.',
      })
    },
    onError: () => {
      toast({
        title: 'Failed to create deck',
        description: 'Please try again or check the server logs for details.',
        variant: 'destructive',
      })
    },
  })
}

export function useUpdateFlashcardDeck() {
  const queryClient = useQueryClient()
  const { toast } = useToast()

  return useMutation({
    mutationFn: ({
      deckId,
      payload,
    }: {
      deckId: string
      payload: FlashcardDeckUpdate
    }) => flashcardsApi.updateDeck(deckId, payload),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.flashcardDeck(variables.deckId) })
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.flashcardDecks })
      toast({
        title: 'Deck updated',
        description: 'Changes saved successfully.',
      })
    },
    onError: () => {
      toast({
        title: 'Failed to update deck',
        description: 'Please try again later.',
        variant: 'destructive',
      })
    },
  })
}

export function useDeleteFlashcardDeck() {
  const queryClient = useQueryClient()
  const { toast } = useToast()

  return useMutation({
    mutationFn: (deckId: string) => flashcardsApi.deleteDeck(deckId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.flashcardDecks })
      toast({
        title: 'Deck deleted',
        description: 'Flashcard deck removed successfully.',
      })
    },
    onError: () => {
      toast({
        title: 'Failed to delete deck',
        description: 'Please try again or check the server logs for details.',
        variant: 'destructive',
      })
    },
  })
}

export function useGenerateFlashcards() {
  const queryClient = useQueryClient()
  const { toast } = useToast()

  return useMutation({
    mutationFn: ({
      deckId,
      payload,
    }: {
      deckId: string
      payload: FlashcardGenerateRequest
    }) => flashcardsApi.generateFlashcards(deckId, payload),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.flashcardDeck(data.job_id) })
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.flashcardDecks })
      toast({
        title: 'Generation started',
        description: 'Flashcard generation is running in the background.',
      })
    },
    onError: (error: Error & { response?: { data?: { detail?: string } } }) => {
      const detail = error.response?.data?.detail || error.message
      toast({
        title: 'Failed to generate flashcards',
        description: detail || 'Please try again or check the server logs for details.',
        variant: 'destructive',
      })
    },
  })
}

// ---------------------------------------------------------------------------
// Card hooks
// ---------------------------------------------------------------------------

export function useFlashcardCards(deckId: string) {
  const query = useQuery({
    queryKey: QUERY_KEYS.flashcardDeckCards(deckId),
    queryFn: () => flashcardsApi.getDeckCards(deckId),
    enabled: !!deckId,
  })

  return {
    ...query,
    cards: query.data ?? [],
  }
}

export function useCreateFlashcard() {
  const queryClient = useQueryClient()
  const { toast } = useToast()

  return useMutation({
    mutationFn: (payload: FlashcardCreate) =>
      flashcardsApi.createCard(payload),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.flashcardDeckCards(data.deck_id) })
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.flashcardDeck(data.deck_id) })
      toast({
        title: 'Card created',
        description: 'Flashcard added to deck.',
      })
    },
    onError: () => {
      toast({
        title: 'Failed to create card',
        description: 'Please try again or check the server logs for details.',
        variant: 'destructive',
      })
    },
  })
}

// ---------------------------------------------------------------------------
// Session hooks
// ---------------------------------------------------------------------------

export function useFlashcardSession(sessionId: string) {
  const query = useQuery({
    queryKey: QUERY_KEYS.flashcardSession(sessionId),
    queryFn: () => flashcardsApi.getSession(sessionId),
    enabled: !!sessionId,
  })

  return {
    ...query,
    session: query.data,
  }
}

export function useCreateFlashcardSession() {
  const queryClient = useQueryClient()
  const { toast } = useToast()

  return useMutation({
    mutationFn: (deckId: string) =>
      flashcardsApi.createSession(deckId),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.flashcardSessions(data.deck_id) })
      toast({
        title: 'Session started',
        description: 'Good luck with your study session!',
      })
    },
    onError: () => {
      toast({
        title: 'Failed to start session',
        description: 'Please try again or check the server logs for details.',
        variant: 'destructive',
      })
    },
  })
}

export function useSubmitFlashcardAnswer() {
  const queryClient = useQueryClient()
  const { toast } = useToast()

  return useMutation({
    mutationFn: ({
      sessionId,
      payload,
    }: {
      sessionId: string
      payload: FlashcardAnswerSubmit
    }) => flashcardsApi.submitAnswer(sessionId, payload),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.flashcardSession(data.id) })
    },
    onError: () => {
      toast({
        title: 'Failed to submit answer',
        description: 'Please try again.',
        variant: 'destructive',
      })
    },
  })
}

export function useCompleteFlashcardSession() {
  const queryClient = useQueryClient()
  const { toast } = useToast()

  return useMutation({
    mutationFn: (sessionId: string) =>
      flashcardsApi.completeSession(sessionId),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.flashcardSession(data.id) })
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.flashcardSessions(data.deck_id) })
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.flashcardDeck(data.deck_id) })
      toast({
        title: 'Session completed',
        description: `Your score: ${data.score}% (${data.correct_count}/${data.total_cards} correct)`,
      })
    },
    onError: () => {
      toast({
        title: 'Failed to complete session',
        description: 'Please try again.',
        variant: 'destructive',
      })
    },
  })
}

export function useFlashcardDeckSessions(deckId: string) {
  const query = useQuery({
    queryKey: QUERY_KEYS.flashcardSessions(deckId),
    queryFn: () => flashcardsApi.getDeckSessions(deckId),
    enabled: !!deckId,
  })

  return {
    ...query,
    sessions: query.data ?? [],
  }
}

export function useFlashcardDeckStats(deckId: string) {
  const query = useQuery({
    queryKey: ['flashcards', 'stats', deckId] as const,
    queryFn: () => flashcardsApi.getDeckStats(deckId),
    enabled: !!deckId,
  })

  return {
    ...query,
    stats: query.data,
  }
}
