export interface SpeakerConfig {
  name: string
  role: string
  personality: string
  backstory: string
  voice_id?: string
}

export interface TranscriptTurn {
  speaker: string
  text: string
  timestamp?: string
}

export interface StudioSession {
  session_id: string
  briefing: string
  notebook_id?: string
  speakers: SpeakerConfig[]
  transcript: TranscriptTurn[]
  turn_count: number
  status: 'completed' | 'stopped' | 'error'
  created_at: string
  fact_check_mode: 'none' | 'notebook' | 'internet' | 'both'
}

export interface StudioSessionListItem {
  session_id: string
  briefing: string
  notebook_id?: string
  speakers: SpeakerConfig[]
  turn_count: number
  status: string
  created_at: string
  fact_check_mode: string
}

export type StudioSessionListResponse = StudioSessionListItem[]
