// Flashcard types for the Pwinbook flashcard feature

export interface FlashcardDeck {
  id: string
  name: string
  description?: string
  notebook_id?: string
  auto_generated: boolean
  card_count?: number
  cards_new?: number
  cards_due?: number
  cards_learned?: number
  job_status_override?: string | null
  created?: string
  updated?: string
}

export interface Flashcard {
  id: string
  deck_id: string
  card_type?: 'basic' | 'cloze' | 'reverse' | 'multiple_choice'
  question: string
  answer: string
  cloze_text?: string
  choices?: string[]
  correct_choice_index?: number
  hints?: string[]
  explanation?: string
  difficulty?: 'easy' | 'medium' | 'hard'
  tags?: string[]
  // SRS fields
  srs_stage?: 'new' | 'learning' | 'review' | 'relearning'
  srs_repetitions?: number
  srs_interval?: number
  srs_ease_factor?: number
  srs_due_date?: string
  mastery?: number
  times_correct?: number
  times_incorrect?: number
}

export interface FlashcardSession {
  id: string
  deck_id: string
  user_answers: Array<{
    card_id: string
    user_answer: string
    correct: boolean
    timestamp?: string
  }>
  score: number
  started_at: string
  completed_at?: string
  total_cards: number
  correct_count: number
}

export interface FlashcardDeckCreate {
  name: string
  description?: string
  notebook_id?: string
}

export interface FlashcardDeckUpdate {
  name?: string
  description?: string
}

export interface FlashcardGenerateRequest {
  notebook_id: string
  num_cards?: number
  deck_name?: string
  deck_description?: string
}

export interface FlashcardCreate {
  deck_id: string
  question: string
  answer: string
  hints?: string[]
  difficulty?: string
  tags?: string[]
}

export interface FlashcardAnswerSubmit {
  card_id: string
  user_answer: string
  correct: boolean
}

export interface DeckStats {
  total_sessions: number
  avg_score: number
  best_score: number
  worst_score: number
}

export interface JobStatus {
  job_id: string
  status: string
  error?: string
  message?: string
  card_count?: number
  deck_name?: string
  notebook_id?: string
  is_running?: boolean
}
