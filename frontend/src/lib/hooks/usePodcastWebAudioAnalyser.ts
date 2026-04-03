'use client'

import { useCallback, useEffect, useRef, type RefObject } from 'react'

/**
 * One MediaElementAudioSourceNode per HTMLMediaElement — connect on first `play`,
 * route audio through AnalyserNode for visualization, then to speakers.
 */
export function usePodcastWebAudioAnalyser(
  audioRef: RefObject<HTMLAudioElement | null>,
  audioSrc: string | undefined
) {
  const analyserRef = useRef<AnalyserNode | null>(null)
  const ctxRef = useRef<AudioContext | null>(null)
  const connectedRef = useRef(false)

  const resetGraph = useCallback(() => {
    connectedRef.current = false
    analyserRef.current = null
    const ctx = ctxRef.current
    ctxRef.current = null
    void ctx?.close().catch(() => {})
  }, [])

  useEffect(() => {
    if (!audioSrc) {
      resetGraph()
      return
    }

    resetGraph()

    const audio = audioRef.current
    if (!audio) return

    const AudioCtx =
      typeof window !== 'undefined'
        ? window.AudioContext ||
          (
            window as typeof window & {
              webkitAudioContext?: typeof AudioContext
            }
          ).webkitAudioContext
        : null

    if (!AudioCtx) return

    const ensureGraph = () => {
      if (connectedRef.current || !audioRef.current) return
      try {
        const ctx = new AudioCtx()
        const source = ctx.createMediaElementSource(audioRef.current)
        const analyser = ctx.createAnalyser()
        analyser.fftSize = 512
        analyser.smoothingTimeConstant = 0.78
        analyser.minDecibels = -90
        analyser.maxDecibels = -15
        source.connect(analyser)
        analyser.connect(ctx.destination)
        ctxRef.current = ctx
        analyserRef.current = analyser
        connectedRef.current = true
      } catch (e) {
        console.warn('[podcast] Web Audio setup failed (visualizer only)', e)
      }
    }

    const onPlay = () => {
      ensureGraph()
      void ctxRef.current?.resume().catch(() => {})
    }

    audio.addEventListener('play', onPlay)
    return () => {
      audio.removeEventListener('play', onPlay)
    }
  }, [audioRef, audioSrc, resetGraph])

  useEffect(() => {
    return () => resetGraph()
  }, [resetGraph])

  return { analyserRef }
}
