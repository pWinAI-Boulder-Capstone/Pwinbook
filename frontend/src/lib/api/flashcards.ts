import apiClient from './client'
import type {
  FlashcardDeck,
  Flashcard,
  FlashcardSession,
  FlashcardDeckCreate,
  FlashcardDeckUpdate,
  FlashcardGenerateRequest,
  FlashcardCreate,
  FlashcardAnswerSubmit,
  DeckStats,
  JobStatus,
} from '@/lib/types/flashcards'

export const flashcardsApi = {
  // Deck operations
  listDecks: async (notebookId?: string) => {
    const params = notebookId ? { notebook_id: notebookId } : {}
    const response = await apiClient.get<FlashcardDeck[]>('/flashcards/decks', { params })
    return response.data
  },

  getDeck: async (deckId: string) => {
    const response = await apiClient.get<FlashcardDeck>(`/flashcards/decks/${deckId}`)
    return response.data
  },

  createDeck: async (payload: FlashcardDeckCreate) => {
    const response = await apiClient.post<FlashcardDeck>('/flashcards/decks', payload)
    return response.data
  },

  updateDeck: async (deckId: string, payload: FlashcardDeckUpdate) => {
    const response = await apiClient.put<FlashcardDeck>(`/flashcards/decks/${deckId}`, payload)
    return response.data
  },

  deleteDeck: async (deckId: string) => {
    await apiClient.delete(`/flashcards/decks/${deckId}`)
  },

  generateFlashcards: async (deckId: string, payload: FlashcardGenerateRequest) => {
    const response = await apiClient.post<{ job_id: string; status: string; message: string }>(
      `/flashcards/decks/${deckId}/generate`,
      payload
    )
    return response.data
  },

  getJobStatus: async (jobId: string) => {
    const response = await apiClient.get<JobStatus>(`/flashcards/jobs/${jobId}`)
    return response.data
  },

  // Card operations
  getDeckCards: async (deckId: string) => {
    const response = await apiClient.get<Flashcard[]>(`/flashcards/decks/${deckId}/cards`)
    return response.data
  },

  createCard: async (payload: FlashcardCreate) => {
    const response = await apiClient.post<Flashcard>(`/flashcards/decks/${payload.deck_id}/cards`, payload)
    return response.data
  },

  // Session operations
  createSession: async (deckId: string) => {
    const response = await apiClient.post<FlashcardSession>('/flashcards/sessions', {
      deck_id: deckId,
    })
    return response.data
  },

  getSession: async (sessionId: string) => {
    const response = await apiClient.get<FlashcardSession>(`/flashcards/sessions/${sessionId}`)
    return response.data
  },

  submitAnswer: async (sessionId: string, payload: FlashcardAnswerSubmit) => {
    const response = await apiClient.post<FlashcardSession>(
      `/flashcards/sessions/${sessionId}/answer`,
      payload
    )
    return response.data
  },

  completeSession: async (sessionId: string) => {
    const response = await apiClient.post<FlashcardSession>(
      `/flashcards/sessions/${sessionId}/complete`
    )
    return response.data
  },

  getDeckSessions: async (deckId: string, limit: number = 5) => {
    const response = await apiClient.get<FlashcardSession[]>(
      `/flashcards/sessions/deck/${deckId}`,
      { params: { limit } }
    )
    return response.data
  },

  // Stats
  getDeckStats: async (deckId: string) => {
    const response = await apiClient.get<DeckStats>(`/flashcards/decks/${deckId}/stats`)
    return response.data
  },
}
