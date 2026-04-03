'use client'

import { useEffect, useState } from 'react'

import { resolvePodcastAssetUrl } from '@/lib/api/podcasts'

type EpisodeAudioFields = {
  audio_url?: string | null
  audio_file?: string | null
}

export function usePodcastEpisodeAudio(episode: EpisodeAudioFields | undefined) {
  const [audioSrc, setAudioSrc] = useState<string | undefined>()
  const [audioError, setAudioError] = useState<string | null>(null)

  useEffect(() => {
    if (!episode) {
      setAudioSrc(undefined)
      setAudioError(null)
      return
    }

    let revokeUrl: string | undefined
    setAudioError(null)

    const loadProtectedAudio = async () => {
      const directAudioUrl = await resolvePodcastAssetUrl(
        episode.audio_url ?? episode.audio_file
      )

      if (!directAudioUrl || !episode.audio_url) {
        setAudioSrc(directAudioUrl)
        return
      }

      try {
        let token: string | undefined
        if (typeof window !== 'undefined') {
          const raw = window.localStorage.getItem('auth-storage')
          if (raw) {
            try {
              const parsed = JSON.parse(raw)
              token = parsed?.state?.token
            } catch (error) {
              console.error('Failed to parse auth storage', error)
            }
          }
        }

        const headers: HeadersInit = {}
        if (token) {
          headers.Authorization = `Bearer ${token}`
        }

        const response = await fetch(directAudioUrl, { headers })
        if (!response.ok) {
          throw new Error(`Audio request failed with status ${response.status}`)
        }

        const blob = await response.blob()
        revokeUrl = URL.createObjectURL(blob)
        setAudioSrc(revokeUrl)
      } catch (error) {
        console.error('Unable to load podcast audio', error)
        setAudioError('Audio unavailable')
        setAudioSrc(undefined)
      }
    }

    void loadProtectedAudio()

    return () => {
      if (revokeUrl) {
        URL.revokeObjectURL(revokeUrl)
      }
    }
  }, [episode?.audio_file, episode?.audio_url])

  return { audioSrc, audioError }
}
