'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

import { getApiUrl } from '@/lib/config'
import { useAuthStore } from '@/lib/stores/auth-store'
import type {
  ClientMessage,
  ConversationMessage,
  PodcastStartConfig,
  ServerMessage,
  SpeakerConfig,
  StudioStatus,
} from '@/lib/types/podcast-studio-ws'

let _msgCounter = 0
function uid() {
  return `msg-${++_msgCounter}`
}

// Map speaker names -> stable color index (0-3)
function makeSpeakerColorMap(speakers: SpeakerConfig[]): Record<string, number> {
  const map: Record<string, number> = {}
  speakers.forEach((s, i) => {
    map[s.name] = i % 4
  })
  return map
}

// ---------------------------------------------------------------------------
// Reconnection constants
// ---------------------------------------------------------------------------
const RECONNECT_BASE_MS = 1000
const RECONNECT_MAX_MS = 16000
const RECONNECT_MAX_ATTEMPTS = 5

export interface UsePodcastStudioWsResult {
  messages: ConversationMessage[]
  activeSpeaker: string | null
  status: StudioStatus
  start: (config: PodcastStartConfig) => Promise<void>
  interrupt: (message: string) => void
  stop: () => void
  reset: () => void
}

export function usePodcastStudioWs(): UsePodcastStudioWsResult {
  const wsRef = useRef<WebSocket | null>(null)
  const colorMapRef = useRef<Record<string, number>>({})
  const configRef = useRef<PodcastStartConfig | null>(null)
  const reconnectAttemptRef = useRef(0)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Track whether the user explicitly stopped or reset (suppress reconnect)
  const intentionalCloseRef = useRef(false)

  const [messages, setMessages] = useState<ConversationMessage[]>([])
  const [activeSpeaker, setActiveSpeaker] = useState<string | null>(null)
  const [status, setStatus] = useState<StudioStatus>('idle')

  // Clean up on unmount
  useEffect(() => {
    return () => {
      intentionalCloseRef.current = true
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
      wsRef.current?.close()
    }
  }, [])

  // -----------------------------------------------------------------------
  // Core WebSocket connection builder (shared by start and reconnect)
  // -----------------------------------------------------------------------
  const connectWs = useCallback(async (config: PodcastStartConfig, isReconnect: boolean) => {
    // Close stale socket if any
    wsRef.current?.close()
    wsRef.current = null

    if (!isReconnect) {
      setMessages([])
      setActiveSpeaker(null)
    }
    setStatus('connecting')

    colorMapRef.current = makeSpeakerColorMap(config.speakers)

    try {
      const apiUrl = await getApiUrl()
      // Convert http(s):// -> ws(s)://
      const wsBase = apiUrl.replace(/^http/, 'ws')

      // Fix 5: Append auth token as query parameter if available
      const authToken = useAuthStore.getState().token
      let wsUrl = `${wsBase}/api/ws/podcast-studio`
      if (authToken && authToken !== 'not-required') {
        wsUrl += `?token=${encodeURIComponent(authToken)}`
      }

      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        // Reset reconnect counter on successful connection
        reconnectAttemptRef.current = 0

        // Send start message immediately after connection
        const startMsg: ClientMessage = { type: 'start', ...config }
        ws.send(JSON.stringify(startMsg))
        setStatus('active')

        if (isReconnect) {
          setMessages((prev) => [
            ...prev,
            { type: 'system', id: uid(), text: 'Reconnected to studio.' },
          ])
        }
      }

      ws.onerror = () => {
        // Only show error if this is not going to be followed by a reconnect
        if (intentionalCloseRef.current) {
          setStatus('error')
          setMessages((prev) => [
            ...prev,
            { type: 'system', id: uid(), text: 'Connection error. Please try again.' },
          ])
        }
      }

      ws.onclose = (event) => {
        if (wsRef.current === ws) {
          wsRef.current = null
        }
        setActiveSpeaker(null)

        // Attempt reconnection if:
        //  - close was NOT intentional (user didn't click Stop/Reset)
        //  - we haven't exhausted reconnect attempts
        //  - close code is not a normal or auth-failure code
        const isAuthFailure = event.code === 4003
        if (
          !intentionalCloseRef.current &&
          !isAuthFailure &&
          reconnectAttemptRef.current < RECONNECT_MAX_ATTEMPTS &&
          configRef.current
        ) {
          const attempt = reconnectAttemptRef.current
          const delay = Math.min(
            RECONNECT_BASE_MS * Math.pow(2, attempt),
            RECONNECT_MAX_MS,
          )
          reconnectAttemptRef.current = attempt + 1
          setStatus('connecting')
          setMessages((prev) => [
            ...prev,
            {
              type: 'system',
              id: uid(),
              text: `Connection lost. Reconnecting in ${Math.round(delay / 1000)}s (attempt ${attempt + 1}/${RECONNECT_MAX_ATTEMPTS})...`,
            },
          ])
          reconnectTimerRef.current = setTimeout(() => {
            if (configRef.current) {
              connectWs(configRef.current, true)
            }
          }, delay)
        } else if (isAuthFailure) {
          setStatus('error')
          setMessages((prev) => [
            ...prev,
            { type: 'system', id: uid(), text: 'Authentication failed. Please log in and try again.' },
          ])
        } else if (
          !intentionalCloseRef.current &&
          reconnectAttemptRef.current >= RECONNECT_MAX_ATTEMPTS
        ) {
          setStatus('error')
          setMessages((prev) => [
            ...prev,
            { type: 'system', id: uid(), text: 'Could not reconnect after multiple attempts.' },
          ])
        }
      }

      ws.onmessage = (event) => {
        let msg: ServerMessage
        try {
          msg = JSON.parse(event.data as string)
        } catch {
          return
        }

        switch (msg.type) {
          case 'connected':
            // session_id received -- nothing to do in UI
            break

          case 'turn_start': {
            const colorIndex = colorMapRef.current[msg.speaker] ?? 0
            setActiveSpeaker(msg.speaker)
            setMessages((prev) => [
              ...prev,
              {
                type: 'speaker',
                id: uid(),
                speaker: msg.speaker,
                colorIndex,
                text: '',
                streaming: true,
              },
            ])
            break
          }

          case 'token': {
            // Append token to the last streaming speaker bubble
            setMessages((prev) => {
              const last = prev[prev.length - 1]
              if (
                last &&
                last.type === 'speaker' &&
                last.speaker === msg.speaker &&
                last.streaming
              ) {
                return [
                  ...prev.slice(0, -1),
                  { ...last, text: last.text + msg.token },
                ]
              }
              // Fallback: append new bubble if no matching streaming bubble
              const colorIndex = colorMapRef.current[msg.speaker] ?? 0
              return [
                ...prev,
                {
                  type: 'speaker',
                  id: uid(),
                  speaker: msg.speaker,
                  colorIndex,
                  text: msg.token,
                  streaming: true,
                },
              ]
            })
            break
          }

          case 'turn_end': {
            setActiveSpeaker(null)
            // Mark last speaker bubble as done streaming
            setMessages((prev) => {
              const last = prev[prev.length - 1]
              if (last && last.type === 'speaker' && last.streaming) {
                return [...prev.slice(0, -1), { ...last, streaming: false }]
              }
              return prev
            })
            break
          }

          case 'turn_cancel': {
            setActiveSpeaker(null)
            // Remove the empty streaming bubble that was speculatively created
            setMessages((prev) => {
              const last = prev[prev.length - 1]
              if (last && last.type === 'speaker' && last.streaming && last.text === '') {
                return prev.slice(0, -1)
              }
              return prev
            })
            break
          }

          case 'user_message': {
            setMessages((prev) => [
              ...prev,
              { type: 'user', id: uid(), text: msg.text },
            ])
            break
          }

          case 'fact_check': {
            if (msg.status === 'searching') {
              setStatus('fact_checking')
              setMessages((prev) => [
                ...prev,
                { type: 'fact_check', id: uid(), status: 'searching', query: msg.query },
              ])
            } else {
              setStatus('active')
              // Update the last searching fact_check message to done with results
              setMessages((prev) => {
                const idx = [...prev].reverse().findIndex((m) => m.type === 'fact_check' && m.status === 'searching')
                if (idx === -1) return prev
                const realIdx = prev.length - 1 - idx
                const updated = [...prev]
                updated[realIdx] = {
                  ...updated[realIdx],
                  status: 'done',
                  query: msg.query,
                  results: msg.results,
                  source: msg.source,
                } as ConversationMessage
                return updated
              })
            }
            break
          }

          case 'consensus_check': {
            setStatus('consensus_checking')
            setMessages((prev) => {
              const last = prev[prev.length - 1]
              if (last?.type === 'system' && last.text?.includes('consensus')) return prev
              return [...prev, { type: 'system', id: uid(), text: 'Checking if the panel has reached consensus...' }]
            })
            break
          }

          case 'consensus_reached': {
            setStatus('done')
            setActiveSpeaker(null)
            // Prevent reconnect on normal completion
            intentionalCloseRef.current = true
            setMessages((prev) => [
              ...prev,
              { type: 'consensus', id: uid(), summary: msg.summary },
            ])
            break
          }

          case 'error': {
            setStatus('error')
            setMessages((prev) => [
              ...prev,
              { type: 'system', id: uid(), text: `Error: ${msg.message}` },
            ])
            break
          }
        }
      }
    } catch (err) {
      setStatus('error')
      setMessages((prev) => [
        ...prev,
        { type: 'system', id: uid(), text: `Failed to connect: ${String(err)}` },
      ])
    }
  }, [])

  const reset = useCallback(() => {
    intentionalCloseRef.current = true
    if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
    wsRef.current?.close()
    wsRef.current = null
    configRef.current = null
    reconnectAttemptRef.current = 0
    setMessages([])
    setActiveSpeaker(null)
    setStatus('idle')
  }, [])

  const interrupt = useCallback((message: string) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return
    const msg: ClientMessage = { type: 'interrupt', message }
    wsRef.current.send(JSON.stringify(msg))
  }, [])

  const stop = useCallback(() => {
    intentionalCloseRef.current = true
    if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return
    const msg: ClientMessage = { type: 'stop' }
    wsRef.current.send(JSON.stringify(msg))
    setStatus('idle')
  }, [])

  const start = useCallback(async (config: PodcastStartConfig) => {
    intentionalCloseRef.current = false
    reconnectAttemptRef.current = 0
    if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
    configRef.current = config
    await connectWs(config, false)
  }, [connectWs])

  return { messages, activeSpeaker, status, start, interrupt, stop, reset }
}
