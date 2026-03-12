import type { StudioSession, StudioSessionListResponse } from '@/lib/types/studio-sessions'
import { apiClient } from './client'

export async function listStudioSessions(params?: {
  notebook_id?: string
  limit?: number
  offset?: number
  search?: string
}): Promise<StudioSessionListResponse> {
  const searchParams = new URLSearchParams()
  if (params?.notebook_id) searchParams.set('notebook_id', params.notebook_id)
  if (params?.limit) searchParams.set('limit', params.limit.toString())
  if (params?.offset) searchParams.set('offset', params.offset.toString())
  if (params?.search) searchParams.set('search', params.search)

  const query = searchParams.toString()
  return apiClient.get(`/studio-sessions${query ? `?${query}` : ''}`)
}

export async function getStudioSession(sessionId: string): Promise<StudioSession> {
  return apiClient.get(`/studio-sessions/${sessionId}`)
}

export async function deleteStudioSession(sessionId: string): Promise<void> {
  return apiClient.delete(`/studio-sessions/${sessionId}`)
}

export function getStudioSessionExportUrl(sessionId: string, format: 'txt' | 'md' | 'json'): string {
  return `${window.location.origin}/api/studio-sessions/${sessionId}/export?format=${format}`
}
