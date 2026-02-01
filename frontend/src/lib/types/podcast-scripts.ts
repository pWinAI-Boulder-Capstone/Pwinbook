export type SegmentSize = 'short' | 'medium' | 'long'
export type FactCheckMode = 'none' | 'notebook' | 'internet' | 'both'

export type AgentTraceEvent = {
  step: string
  mode?: FactCheckMode
  provider?: string
  query?: string
  max_results?: number
  results?: number
  found_nothing?: boolean
  urls?: string[]
  reason?: string
  error?: string
}

export interface PodcastScriptOutlineSegment {
  name: string
  description: string
  size: SegmentSize
}

export interface PodcastScriptOutline {
  segments: PodcastScriptOutlineSegment[]
}

export interface PodcastScriptOutlineRequest {
  episode_profile: string
  episode_name: string
  notebook_id?: string
  content?: string
  briefing_suffix?: string | null
  num_segments?: number
  model_override?: string | null
}

export interface PodcastScriptOutlineResponse {
  episode_profile: string
  speaker_profile: string
  episode_name: string
  briefing: string
  outline: PodcastScriptOutline
}

export interface PodcastScriptTranscriptLine {
  speaker: string
  dialogue: string
}

export interface PodcastScriptInteractiveTranscript {
  transcript: PodcastScriptTranscriptLine[]
  questions: string[]
}

export interface PodcastLiveDiscussionRequest {
  episode_profile?: string
  episode_name?: string
  notebook_id?: string
  content?: string
  briefing_suffix?: string | null
  model_override?: string | null

  speakers_override?: Array<{
    name: string
    backstory?: string
    personality?: string
    role?: string
  }>

  transcript_so_far?: PodcastScriptTranscriptLine[]
  turns?: number

  user_message?: string | null
  fact_check_mode?: FactCheckMode
  max_evidence?: number
}

export interface PodcastLiveDiscussionResponse {
  episode_profile: string
  speaker_profile: string
  episode_name: string
  fact_check_mode: FactCheckMode
  trace: AgentTraceEvent[]
  evidence?: Array<Record<string, unknown>> | null
  result: {
    transcript: PodcastScriptTranscriptLine[]
    next_suggestions: string[]
    await_user_question?: string | null
  }
}

export interface PodcastScriptSegmentRequest {
  episode_profile: string
  episode_name: string
  notebook_id?: string
  content?: string
  briefing_suffix?: string | null
  model_override?: string | null

  outline: PodcastScriptOutline
  segment_index: number

  transcript_so_far?: PodcastScriptTranscriptLine[]
  turns?: number
  ask_questions?: boolean
  user_interrupt?: string | null
}

export interface PodcastScriptSegmentResponse {
  episode_profile: string
  speaker_profile: string
  episode_name: string
  segment_index: number
  segment: PodcastScriptOutlineSegment
  result: PodcastScriptInteractiveTranscript
}
