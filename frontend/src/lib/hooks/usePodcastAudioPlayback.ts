'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

const SKIP_SECONDS = 10

export function usePodcastAudioPlayback(audioSrc: string | undefined) {
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const [playing, setPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [rate, setRate] = useState('1')

  useEffect(() => {
    setPlaying(false)
    setCurrentTime(0)
    setDuration(0)
  }, [audioSrc])

  useEffect(() => {
    const a = audioRef.current
    if (!a || !audioSrc) return

    const onDuration = () => {
      const d = a.duration
      setDuration(Number.isFinite(d) ? d : 0)
    }
    const onPlay = () => setPlaying(true)
    const onPause = () => {
      setPlaying(false)
      setCurrentTime(a.currentTime)
    }
    const onEnded = () => {
      setPlaying(false)
      setCurrentTime(Number.isFinite(a.duration) ? a.duration : 0)
    }

    a.addEventListener('durationchange', onDuration)
    a.addEventListener('loadedmetadata', onDuration)
    a.addEventListener('play', onPlay)
    a.addEventListener('pause', onPause)
    a.addEventListener('ended', onEnded)

    a.playbackRate = Number.parseFloat(rate) || 1

    return () => {
      a.removeEventListener('durationchange', onDuration)
      a.removeEventListener('loadedmetadata', onDuration)
      a.removeEventListener('play', onPlay)
      a.removeEventListener('pause', onPause)
      a.removeEventListener('ended', onEnded)
    }
  }, [audioSrc, rate])

  useEffect(() => {
    const a = audioRef.current
    if (a) {
      a.playbackRate = Number.parseFloat(rate) || 1
    }
  }, [rate])

  useEffect(() => {
    if (!playing || !audioSrc) return
    let id = 0
    const tick = () => {
      const a = audioRef.current
      if (a && !a.paused) {
        setCurrentTime(a.currentTime)
      }
      id = requestAnimationFrame(tick)
    }
    id = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(id)
  }, [playing, audioSrc])

  const togglePlay = useCallback(() => {
    const a = audioRef.current
    if (!a || !audioSrc) return
    if (a.paused) {
      void a.play()
    } else {
      a.pause()
    }
  }, [audioSrc])

  const skipBack = useCallback(() => {
    const a = audioRef.current
    if (!a) return
    a.currentTime = Math.max(0, a.currentTime - SKIP_SECONDS)
    setCurrentTime(a.currentTime)
  }, [])

  const skipForward = useCallback(() => {
    const a = audioRef.current
    if (!a) return
    const d = Number.isFinite(a.duration) ? a.duration : a.currentTime + SKIP_SECONDS
    a.currentTime = Math.min(d, a.currentTime + SKIP_SECONDS)
    setCurrentTime(a.currentTime)
  }, [])

  const seekToProgress = useCallback((progress0to1000: number) => {
    const a = audioRef.current
    if (!a || !Number.isFinite(a.duration) || a.duration <= 0) return
    const next = (progress0to1000 / 1000) * a.duration
    a.currentTime = next
    setCurrentTime(next)
  }, [])

  return {
    audioRef,
    playing,
    currentTime,
    duration,
    rate,
    setRate,
    togglePlay,
    skipBack,
    skipForward,
    seekToProgress,
    skipSeconds: SKIP_SECONDS,
  }
}
