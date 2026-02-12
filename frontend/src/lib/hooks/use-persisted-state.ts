'use client'

import { useState, useEffect, useCallback, useRef } from 'react'

/**
 * A hook that persists state to localStorage.
 * On mount, reads the saved value; on change, writes it back.
 * Falls back to `defaultValue` if nothing is stored or parsing fails.
 */
export function usePersistedState<T>(key: string, defaultValue: T): [T, (value: T | ((prev: T) => T)) => void] {
  const [state, setState] = useState<T>(defaultValue)
  const isInitialized = useRef(false)

  // Read from localStorage on mount (client-side only)
  useEffect(() => {
    try {
      const stored = localStorage.getItem(key)
      if (stored !== null) {
        setState(JSON.parse(stored) as T)
      }
    } catch {
      // Ignore parse errors, keep default
    }
    isInitialized.current = true
  }, [key])

  // Write to localStorage whenever state changes (skip initial mount)
  useEffect(() => {
    if (!isInitialized.current) return
    try {
      localStorage.setItem(key, JSON.stringify(state))
    } catch {
      // Ignore quota errors
    }
  }, [key, state])

  return [state, setState]
}

const STUDIO_STORAGE_KEY = 'pwinbook:podcast-studio-settings'

export interface PodcastStudioSettings {
  notebookId: string
  episodeProfileName: string
  episodeName: string
  briefingSuffix: string
  mode: 'segmented' | 'live'
  factCheckMode: string
  turnsPerStep: number
  continuousLive: boolean
  useCustomSpeakers: boolean
  customSpeakers: Array<{ name: string; role: string; personality: string }>
  simulateRealtime: boolean
  realtimeDelayMs: number
  useServerStreaming: boolean
}

const DEFAULT_SETTINGS: PodcastStudioSettings = {
  notebookId: '',
  episodeProfileName: '',
  episodeName: '',
  briefingSuffix: '',
  mode: 'live',
  factCheckMode: 'both',
  turnsPerStep: 6,
  continuousLive: true,
  useCustomSpeakers: true,
  customSpeakers: [
    { name: 'Host', role: 'Optimistic host who keeps the flow moving', personality: 'Curious, upbeat, concise' },
    { name: 'Analyst', role: 'Skeptical analyst who challenges claims', personality: 'Precise, evidence-driven, polite' },
  ],
  simulateRealtime: true,
  realtimeDelayMs: 220,
  useServerStreaming: true,
}

/**
 * Load podcast studio settings from localStorage.
 * Returns defaults merged with any saved values.
 */
export function loadStudioSettings(): PodcastStudioSettings {
  try {
    const stored = localStorage.getItem(STUDIO_STORAGE_KEY)
    if (stored) {
      const parsed = JSON.parse(stored)
      // Merge with defaults so new fields get their default values
      return { ...DEFAULT_SETTINGS, ...parsed }
    }
  } catch {
    // Ignore
  }
  return { ...DEFAULT_SETTINGS }
}

/**
 * Save podcast studio settings to localStorage.
 */
export function saveStudioSettings(settings: Partial<PodcastStudioSettings>): void {
  try {
    const current = loadStudioSettings()
    const merged = { ...current, ...settings }
    localStorage.setItem(STUDIO_STORAGE_KEY, JSON.stringify(merged))
  } catch {
    // Ignore quota errors
  }
}

/**
 * Hook that provides podcast studio settings with auto-persistence.
 * Reads on mount, provides a save function for batched updates.
 */
export function usePodcastStudioSettings() {
  const [settings, setSettings] = useState<PodcastStudioSettings>(DEFAULT_SETTINGS)
  const isLoaded = useRef(false)

  // Load from localStorage on mount
  useEffect(() => {
    setSettings(loadStudioSettings())
    isLoaded.current = true
  }, [])

  const save = useCallback((updates: Partial<PodcastStudioSettings>) => {
    setSettings(prev => {
      const next = { ...prev, ...updates }
      saveStudioSettings(next)
      return next
    })
  }, [])

  return { settings, save, isLoaded: isLoaded.current }
}
