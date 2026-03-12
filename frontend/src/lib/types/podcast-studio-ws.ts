// ---------------------------------------------------------------------------
// WebSocket message types for the live podcast studio
// ---------------------------------------------------------------------------

// ---- Messages sent by the client ----

export interface PodcastStartConfig {
  speakers: SpeakerConfig[]
  notebook_id: string
  briefing: string          // episode name / topic
  fact_check_mode: FactCheckMode
  model_override?: string | null
}

export interface SpeakerConfig {
  name: string
  role: string
  personality: string
  backstory: string
  model_id?: string   // optional per-speaker model override
}

export type FactCheckMode = 'none' | 'notebook' | 'internet' | 'both'

export type ClientMessage =
  | ({ type: 'start' } & PodcastStartConfig)
  | { type: 'interrupt'; message: string }
  | { type: 'stop' }

// ---- Messages sent by the server ----

export interface SearchResult {
  url: string
  snippet: string
}

export type ServerMessage =
  | { type: 'connected'; session_id: string }
  | { type: 'turn_start'; speaker: string }
  | { type: 'token'; speaker: string; token: string }
  | { type: 'turn_end'; speaker: string }
  | { type: 'turn_cancel'; speaker: string }
  | { type: 'user_message'; text: string }
  | { type: 'fact_check'; status: 'searching'; query?: string }
  | { type: 'fact_check'; status: 'done'; query?: string; results?: SearchResult[]; source?: 'web' | 'notebook' }
  | { type: 'consensus_check' }
  | { type: 'consensus_reached'; summary: string }
  | { type: 'error'; message: string }

// ---- UI conversation message types ----

export type ConversationMessage =
  | {
      type: 'speaker'
      id: string
      speaker: string
      colorIndex: number
      text: string
      streaming: boolean
    }
  | { type: 'user'; id: string; text: string }
  | { type: 'fact_check'; id: string; status: 'searching'; query?: string }
  | { type: 'fact_check'; id: string; status: 'done'; query?: string; results?: SearchResult[]; source?: 'web' | 'notebook' }
  | { type: 'consensus'; id: string; summary: string }
  | { type: 'system'; id: string; text: string }

export type StudioStatus =
  | 'idle'
  | 'connecting'
  | 'active'
  | 'fact_checking'
  | 'consensus_checking'
  | 'done'
  | 'error'

// Speaker color palette indices (0-3)
export const SPEAKER_COLORS = [
  'blue',
  'emerald',
  'violet',
  'amber',
] as const
export type SpeakerColor = typeof SPEAKER_COLORS[number]
