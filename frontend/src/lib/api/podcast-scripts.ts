import apiClient from '@/lib/api/client'
import type {
  PodcastScriptOutlineRequest,
  PodcastScriptOutlineResponse,
  PodcastLiveDiscussionRequest,
  PodcastLiveDiscussionResponse,
  PodcastScriptSegmentRequest,
  PodcastScriptSegmentResponse,
} from '@/lib/types/podcast-scripts'

export const podcastScriptsApi = {
  async generateOutline(payload: PodcastScriptOutlineRequest) {
    const response = await apiClient.post<PodcastScriptOutlineResponse>(
      '/podcast-scripts/outline',
      payload
    )
    return response.data
  },

  async generateSegment(payload: PodcastScriptSegmentRequest) {
    const response = await apiClient.post<PodcastScriptSegmentResponse>(
      '/podcast-scripts/segment',
      payload
    )
    return response.data
  },

  async liveDiscussion(payload: PodcastLiveDiscussionRequest) {
    const response = await apiClient.post<PodcastLiveDiscussionResponse>(
      '/podcast-scripts/live',
      payload
    )
    return response.data
  },
}
