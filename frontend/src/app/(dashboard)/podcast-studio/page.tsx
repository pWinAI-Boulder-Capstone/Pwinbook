
'use client'

import { useEffect, useMemo, useRef, useState } from 'react'

import { AppShell } from '@/components/layout/AppShell'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import { FormSection } from '@/components/ui/form-section'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Label } from '@/components/ui/label'

import { useNotebooks } from '@/lib/hooks/use-notebooks'
import { useEpisodeProfiles } from '@/lib/hooks/use-podcasts'
import { useToast } from '@/lib/hooks/use-toast'
import { loadStudioSettings, saveStudioSettings } from '@/lib/hooks/use-persisted-state'

import type { NotebookResponse } from '@/lib/types/api'
import type { EpisodeProfile } from '@/lib/types/podcasts'

import { podcastScriptsApi } from '@/lib/api/podcast-scripts'
import { getApiUrl } from '@/lib/config'
import type {
  AgentTraceEvent,
  FactCheckMode,
  PodcastScriptOutline,
  PodcastScriptOutlineResponse,
  PodcastScriptTranscriptLine,
  PodcastScriptSegmentResponse,
} from '@/lib/types/podcast-scripts'

function sizeBadgeVariant(size: string): 'default' | 'secondary' | 'outline' {
  if (size === 'short') return 'outline'
  if (size === 'long') return 'default'
  return 'secondary'
}

function getApiErrorDetail(error: unknown): string | undefined {
  if (!error || typeof error !== 'object') return undefined

  const maybeError = error as Record<string, unknown>
  const response = maybeError.response
  if (!response || typeof response !== 'object') return undefined

  const maybeResponse = response as Record<string, unknown>
  const data = maybeResponse.data
  if (!data || typeof data !== 'object') return undefined

  const maybeData = data as Record<string, unknown>
  const detail = maybeData.detail
  return typeof detail === 'string' ? detail : undefined
}

type TraceRow = AgentTraceEvent & { at: string }

function truncateText(value: unknown, maxLen: number): string {
  const text = typeof value === 'string' ? value : ''
  if (text.length <= maxLen) return text
  return `${text.slice(0, Math.max(0, maxLen - 1))}…`
}

function safeUrl(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  if (!trimmed) return null
  if (!/^https?:\/\//i.test(trimmed)) return null
  return trimmed
}

export default function PodcastStudioPage() {
  const { toast } = useToast()

  const { data: notebooks = [], isLoading: notebooksLoading } = useNotebooks(false)
  const { episodeProfiles = [], isLoading: profilesLoading } = useEpisodeProfiles()

  // Load persisted settings from localStorage (falls back to defaults)
  const [savedSettings] = useState(() => loadStudioSettings())

  const [notebookId, setNotebookId] = useState<string>(savedSettings.notebookId)
  const [episodeProfileName, setEpisodeProfileName] = useState<string>(savedSettings.episodeProfileName)
  const [episodeName, setEpisodeName] = useState<string>(savedSettings.episodeName)
  const [briefingSuffix, setBriefingSuffix] = useState<string>(savedSettings.briefingSuffix)

  const [mode, setMode] = useState<'segmented' | 'live'>(savedSettings.mode)

  const [factCheckMode, setFactCheckMode] = useState<FactCheckMode>(savedSettings.factCheckMode as FactCheckMode)
  const [turnsPerStep, setTurnsPerStep] = useState<number>(savedSettings.turnsPerStep)

  const [continuousLive, setContinuousLive] = useState<boolean>(savedSettings.continuousLive)
  const [awaitUserQuestion, setAwaitUserQuestion] = useState<string | null>(null)
  const pendingInterruptRef = useRef<boolean>(false)

  const [useCustomSpeakers, setUseCustomSpeakers] = useState<boolean>(savedSettings.useCustomSpeakers)
  const [customSpeakers, setCustomSpeakers] = useState<
    Array<{ name: string; role: string; personality: string }>
  >(savedSettings.customSpeakers)

  const [simulateRealtime, setSimulateRealtime] = useState<boolean>(savedSettings.simulateRealtime)
  const [realtimeDelayMs, setRealtimeDelayMs] = useState<number>(savedSettings.realtimeDelayMs)
  const liveAppendTimer = useRef<number | null>(null)

  const [useServerStreaming, setUseServerStreaming] = useState<boolean>(savedSettings.useServerStreaming)
  const liveAbortRef = useRef<AbortController | null>(null)

  // Persist settings to localStorage whenever they change
  useEffect(() => {
    saveStudioSettings({
      notebookId,
      episodeProfileName,
      episodeName,
      briefingSuffix,
      mode,
      factCheckMode,
      turnsPerStep,
      continuousLive,
      useCustomSpeakers,
      customSpeakers,
      simulateRealtime,
      realtimeDelayMs,
      useServerStreaming,
    })
  }, [
    notebookId, episodeProfileName, episodeName, briefingSuffix,
    mode, factCheckMode, turnsPerStep, continuousLive,
    useCustomSpeakers, customSpeakers, simulateRealtime,
    realtimeDelayMs, useServerStreaming,
  ])

  const liveSteppingRef = useRef<boolean>(false)
  const awaitUserQuestionRef = useRef<string | null>(null)
  const continuousLiveRef = useRef<boolean>(true)

  useEffect(() => {
    continuousLiveRef.current = continuousLive
  }, [continuousLive])

  const [outlineResponse, setOutlineResponse] = useState<PodcastScriptOutlineResponse | null>(null)
  const [outline, setOutline] = useState<PodcastScriptOutline | null>(null)

  const [segmentIndex, setSegmentIndex] = useState<number>(0)
  const [transcriptSoFar, setTranscriptSoFar] = useState<PodcastScriptTranscriptLine[]>([])
  const [segments, setSegments] = useState<PodcastScriptSegmentResponse[]>([])

  const [askQuestions, setAskQuestions] = useState<boolean>(true)
  const [userInterrupt, setUserInterrupt] = useState<string>('')

  const [isGeneratingOutline, setIsGeneratingOutline] = useState(false)
  const [isGeneratingSegment, setIsGeneratingSegment] = useState(false)
  const [isLiveStepping, setIsLiveStepping] = useState(false)

  const [traceLog, setTraceLog] = useState<TraceRow[]>([])
  const [latestEvidence, setLatestEvidence] = useState<Array<Record<string, unknown>> | null>(null)

  const selectedNotebook = useMemo(
    () => (notebooks as NotebookResponse[]).find((n) => n.id === notebookId),
    [notebooks, notebookId]
  )

  const liveSpeakersOverride = useMemo(
    () =>
      useCustomSpeakers
        ? customSpeakers
            .map((s) => ({ name: s.name.trim(), role: s.role.trim(), personality: s.personality.trim() }))
            .filter((s) => s.name)
        : undefined,
    [useCustomSpeakers, customSpeakers]
  )

  const canGenerateOutline = Boolean(notebookId && episodeProfileName && episodeName)
  const canGenerateSegment = Boolean(outline && segmentIndex < (outline?.segments?.length ?? 0))
  const canLiveStep = Boolean(
    notebookId &&
      episodeName &&
      (episodeProfileName || (useCustomSpeakers && (liveSpeakersOverride?.length ?? 0) > 1))
  )

  const liveMissing: string[] = []
  if (!notebookId) liveMissing.push('Select a notebook')
  if (!episodeProfileName && !(useCustomSpeakers && (liveSpeakersOverride?.length ?? 0) > 1)) {
    liveMissing.push('Select an episode profile OR enable 2+ custom speakers')
  }
  if (!episodeName) liveMissing.push('Set an episode name')

  const resetRun = () => {
    setOutlineResponse(null)
    setOutline(null)
    setSegmentIndex(0)
    setTranscriptSoFar([])
    setSegments([])
    setUserInterrupt('')
    setAwaitUserQuestion(null)
    awaitUserQuestionRef.current = null
    setTraceLog([])
    setLatestEvidence(null)

    if (liveAppendTimer.current) {
      window.clearTimeout(liveAppendTimer.current)
      liveAppendTimer.current = null
    }

    if (liveAbortRef.current) {
      liveAbortRef.current.abort()
      liveAbortRef.current = null
    }

    pendingInterruptRef.current = false
  }

  const suggestEpisodeName = () => {
    if (episodeName.trim()) return
    const base = selectedNotebook?.name ? `Live: ${selectedNotebook.name}` : 'Live: Panel discussion'
    setEpisodeName(base)
  }

  const appendTranscriptLines = (lines: PodcastScriptTranscriptLine[]) => {
    if (!simulateRealtime || lines.length === 0) {
      setTranscriptSoFar((prev) => [...prev, ...lines])
      return
    }

    // If a previous animation is running, finish it instantly.
    if (liveAppendTimer.current) {
      window.clearTimeout(liveAppendTimer.current)
      liveAppendTimer.current = null
    }

    const queue = [...lines]
    const tick = () => {
      const next = queue.shift()
      if (!next) {
        liveAppendTimer.current = null
        return
      }
      setTranscriptSoFar((prev) => [...prev, next])
      liveAppendTimer.current = window.setTimeout(tick, Math.max(40, realtimeDelayMs))
    }
    tick()
  }

  const handleAddSpeaker = () => {
    setCustomSpeakers((prev) => [...prev, { name: `Speaker ${prev.length + 1}`, role: '', personality: '' }])
  }

  const handleRemoveSpeaker = (index: number) => {
    setCustomSpeakers((prev) => prev.filter((_, i) => i !== index))
  }

  const handleUpdateSpeaker = (index: number, key: 'name' | 'role' | 'personality', value: string) => {
    setCustomSpeakers((prev) => prev.map((s, i) => (i === index ? { ...s, [key]: value } : s)))
  }

  const handleGenerateOutline = async () => {
    if (!canGenerateOutline) return

    setIsGeneratingOutline(true)
    try {
      const resp = await podcastScriptsApi.generateOutline({
        episode_profile: episodeProfileName,
        episode_name: episodeName,
        notebook_id: notebookId,
        briefing_suffix: briefingSuffix || null,
      })

      setOutlineResponse(resp)
      setOutline(resp.outline)
      setSegmentIndex(0)
      setTranscriptSoFar([])
      setSegments([])

      toast({
        title: 'Outline generated',
        description: `Created ${resp.outline.segments.length} segments using ${resp.speaker_profile}.`,
      })
    } catch (error: unknown) {
      console.error('[podcast-studio] outline error:', error)
      const detail = getApiErrorDetail(error)
      toast({
        title: 'Failed to generate outline',
        description: detail || 'Please check the backend logs.',
        variant: 'destructive',
      })
    } finally {
      setIsGeneratingOutline(false)
    }
  }

  const handleGenerateNextSegment = async () => {
    if (!outline || !canGenerateSegment) return

    setIsGeneratingSegment(true)
    try {
      const resp = await podcastScriptsApi.generateSegment({
        episode_profile: episodeProfileName,
        episode_name: episodeName,
        notebook_id: notebookId,
        briefing_suffix: briefingSuffix || null,
        outline,
        segment_index: segmentIndex,
        transcript_so_far: transcriptSoFar.length ? transcriptSoFar : undefined,
        turns: 14,
        ask_questions: askQuestions,
        user_interrupt: userInterrupt ? userInterrupt : null,
      })

      setSegments((prev) => [...prev, resp])
      setTranscriptSoFar((prev) => [...prev, ...resp.result.transcript])
      setSegmentIndex((prev) => prev + 1)
      setUserInterrupt('')

      toast({
        title: 'Segment generated',
        description: resp.segment.name,
      })
    } catch (error: unknown) {
      console.error('[podcast-studio] segment error:', error)
      const detail = getApiErrorDetail(error)
      toast({
        title: 'Failed to generate segment',
        description: detail || 'Please check the backend logs.',
        variant: 'destructive',
      })
    } finally {
      setIsGeneratingSegment(false)
    }
  }

  const handleLiveStep = async () => {
    if (mode !== 'live') return
    if (!notebookId || !episodeName) return
    if (!episodeProfileName && !(useCustomSpeakers && (liveSpeakersOverride?.length ?? 0) > 1)) {
      toast({
        title: 'Add speakers or choose a profile',
        description: 'For Live mode, select an episode profile OR enable at least 2 custom speakers.',
        variant: 'destructive',
      })
      return
    }

    // If the panel asked a question, require an answer before continuing.
    if (awaitUserQuestion && !userInterrupt.trim()) {
      toast({
        title: 'Answer the panel to continue',
        description: 'Type your answer in the box, then click Start / Continue.',
        variant: 'destructive',
      })
      return
    }

    setIsLiveStepping(true)
    liveSteppingRef.current = true
    let shouldAutoContinue = false
    try {
      const userMessageToSend = userInterrupt.trim() ? userInterrupt.trim() : undefined
      const payload = {
        ...(episodeProfileName ? { episode_profile: episodeProfileName } : {}),
        ...(episodeName ? { episode_name: episodeName } : {}),
        notebook_id: notebookId,
        briefing_suffix: briefingSuffix || null,
        transcript_so_far: transcriptSoFar.length ? transcriptSoFar.slice(-80) : undefined,
        turns: turnsPerStep,
        ...(userMessageToSend ? { user_message: userMessageToSend } : {}),
        fact_check_mode: factCheckMode,
        speakers_override: liveSpeakersOverride?.map((s) => ({
          name: s.name,
          role: s.role,
          personality: s.personality,
          backstory: s.role,
        })),
      }

      if (useServerStreaming) {
        // Streaming: trace + lines arrive progressively.
        if (liveAbortRef.current) {
          liveAbortRef.current.abort()
          liveAbortRef.current = null
        }

        const controller = new AbortController()
        liveAbortRef.current = controller

        const apiUrl = await getApiUrl()
        const url = `${apiUrl}/api/podcast-scripts/live/stream`

        let authHeader: string | undefined
        if (typeof window !== 'undefined') {
          const authStorage = localStorage.getItem('auth-storage')
          if (authStorage) {
            try {
              const { state } = JSON.parse(authStorage) as { state?: { token?: string } }
              if (state?.token) {
                authHeader = `Bearer ${state.token}`
              }
            } catch {
              // ignore
            }
          }
        }

        const response = await fetch(url, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(authHeader ? { Authorization: authHeader } : {}),
          },
          body: JSON.stringify(payload),
          signal: controller.signal,
        })

        if (!response.ok) {
          const text = await response.text()
          throw new Error(text || `Streaming failed (${response.status})`)
        }

        if (!response.body) {
          throw new Error('Streaming response has no body')
        }

        if (userMessageToSend) {
          setUserInterrupt('')
          setAwaitUserQuestion(null)
          awaitUserQuestionRef.current = null
        }

        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        let receivedAwaitQuestion: string | null = null

        const handleSseChunk = (chunk: string) => {
          const lines = chunk.split('\n')
          let eventName = 'message'
          const dataLines: string[] = []
          for (const line of lines) {
            if (line.startsWith('event:')) {
              eventName = line.slice('event:'.length).trim()
            } else if (line.startsWith('data:')) {
              dataLines.push(line.slice('data:'.length).trim())
            }
          }
          const dataText = dataLines.join('\n')
          if (!dataText) return

          let data: unknown
          try {
            data = JSON.parse(dataText)
          } catch {
            data = dataText
          }

          const at = new Date().toISOString()
          if (eventName === 'trace' && data && typeof data === 'object') {
            setTraceLog((prev) => [...prev, { ...(data as AgentTraceEvent), at }])
          } else if (eventName === 'evidence' && Array.isArray(data)) {
            setLatestEvidence(data as Array<Record<string, unknown>>)
          } else if (eventName === 'line' && data && typeof data === 'object') {
            const obj = data as Record<string, unknown>
            const speaker = typeof obj.speaker === 'string' ? obj.speaker : 'Speaker'
            const dialogue = typeof obj.dialogue === 'string' ? obj.dialogue : ''
            setTranscriptSoFar((prev) => [...prev, { speaker, dialogue }])
          } else if (eventName === 'await_user' && data && typeof data === 'object') {
            const obj = data as Record<string, unknown>
            const q = typeof obj.question === 'string' ? obj.question : ''
            if (q.trim()) {
              receivedAwaitQuestion = q
              setAwaitUserQuestion(q)
              awaitUserQuestionRef.current = q
            }
          } else if (eventName === 'error') {
            const detail =
              data &&
              typeof data === 'object' &&
              'detail' in data &&
              typeof (data as Record<string, unknown>).detail === 'string'
                ? ((data as Record<string, unknown>).detail as string)
                : undefined
            throw new Error(detail || 'Streaming error')
          }
        }

        while (true) {
          const { value, done } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })

          let sepIndex = buffer.indexOf('\n\n')
          while (sepIndex !== -1) {
            const chunk = buffer.slice(0, sepIndex)
            buffer = buffer.slice(sepIndex + 2)
            if (chunk.trim()) {
              handleSseChunk(chunk)
            }
            sepIndex = buffer.indexOf('\n\n')
          }
        }

        toast({
          title: receivedAwaitQuestion ? 'Panel question' : 'Discussion continued',
          description: receivedAwaitQuestion
            ? 'The panel asked you something; answer to continue.'
            : `Streaming complete (${factCheckMode} check).`,
        })
        liveAbortRef.current = null

        shouldAutoContinue = continuousLiveRef.current && !receivedAwaitQuestion
      } else {
        const resp = await podcastScriptsApi.liveDiscussion(payload)
        appendTranscriptLines(resp.result.transcript)
        const at = new Date().toISOString()
        setTraceLog((prev) => [...prev, ...(resp.trace ?? []).map((e: AgentTraceEvent) => ({ ...e, at }))])
        setLatestEvidence(resp.evidence ?? null)
        if (userMessageToSend) {
          setUserInterrupt('')
          setAwaitUserQuestion(null)
          awaitUserQuestionRef.current = null
        }

        if (resp.result.await_user_question) {
          setAwaitUserQuestion(resp.result.await_user_question)
          awaitUserQuestionRef.current = resp.result.await_user_question
        }

        toast({
          title: 'Discussion continued',
          description: `${resp.result.transcript.length} new turns added (${resp.fact_check_mode} check).`,
        })

        shouldAutoContinue = continuousLiveRef.current && !resp.result.await_user_question
      }
    } catch (error: unknown) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        shouldAutoContinue = false
        if (pendingInterruptRef.current) {
          pendingInterruptRef.current = false
          // Immediately restart with the user's typed message.
          window.setTimeout(() => {
            void handleLiveStep()
          }, 0)
        } else {
          toast({
            title: 'Stopped',
            description: 'Live generation was interrupted.',
          })
        }
        return
      }
      console.error('[podcast-studio] live error:', error)
      const detail = getApiErrorDetail(error)
      toast({
        title: 'Failed to continue discussion',
        description: detail || (error instanceof Error ? error.message : 'Please check the backend logs.'),
        variant: 'destructive',
      })
    } finally {
      setIsLiveStepping(false)
      liveSteppingRef.current = false

      // Auto-continue once the current request fully completes.
      if (
        shouldAutoContinue &&
        !awaitUserQuestionRef.current &&
        !pendingInterruptRef.current
      ) {
        window.setTimeout(() => {
          if (!liveSteppingRef.current && continuousLiveRef.current && !awaitUserQuestionRef.current) {
            void handleLiveStep()
          }
        }, 80)
      }
    }
  }

  const lastQuestions = segments.at(-1)?.result.questions ?? []

  const effectiveSpeakerNames = useCustomSpeakers
    ? customSpeakers.map((s) => s.name).filter(Boolean)
    : outlineResponse?.speaker_profile
      ? [outlineResponse.speaker_profile]
      : []

  return (
    <AppShell>
      <div className="flex-1 overflow-y-auto">
        <div className="px-6 py-6 space-y-6">
          <header className="space-y-1">
            <h1 className="text-2xl font-semibold tracking-tight">Podcast Studio (Agentic Script)</h1>
            <p className="text-muted-foreground">
              Live, interruptible multi-speaker discussion with optional fact-check (notebook-only or internet).
            </p>
          </header>

          <Card>
            <CardHeader>
              <CardTitle>Mode</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <RadioGroup value={mode} onValueChange={(v) => setMode(v as 'segmented' | 'live')}>
                <div className="flex items-center space-x-2">
                  <RadioGroupItem value="live" id="mode-live" />
                  <Label htmlFor="mode-live">Live discussion (interrupt anytime)</Label>
                </div>
                <div className="flex items-center space-x-2">
                  <RadioGroupItem value="segmented" id="mode-seg" />
                  <Label htmlFor="mode-seg">Segmented outline (pause after each segment)</Label>
                </div>
              </RadioGroup>

              <div className="grid gap-4 md:grid-cols-3">
                <div className="space-y-2">
                  <Label>Fact-check mode</Label>
                  <Select value={factCheckMode} onValueChange={(v) => setFactCheckMode(v as FactCheckMode)}>
                    <SelectTrigger>
                      <SelectValue placeholder="Select" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="notebook">Notebook only</SelectItem>
                      <SelectItem value="both">Notebook + Internet</SelectItem>
                      <SelectItem value="internet">Internet (Tavily)</SelectItem>
                      <SelectItem value="none">None</SelectItem>
                    </SelectContent>
                  </Select>
                  <p className="text-xs text-muted-foreground">
                    Internet mode uses the server env var TAVILY_API_KEY. If it’s missing, “Continue” will return an API error.
                  </p>
                </div>

                <div className="space-y-2">
                  <Label>Turns per step</Label>
                  <Input
                    type="number"
                    min={2}
                    max={40}
                    value={turnsPerStep}
                    onChange={(e) => setTurnsPerStep(Number(e.target.value) || 6)}
                  />
                  <p className="text-xs text-muted-foreground">
                    Smaller = easier to interrupt “mid conversation”.
                  </p>
                </div>

                <div className="space-y-2">
                  <Label>Speakers</Label>
                  <div className="flex items-center gap-2">
                    <Checkbox
                      id="customSpeakers"
                      checked={useCustomSpeakers}
                      onCheckedChange={(v) => setUseCustomSpeakers(Boolean(v))}
                    />
                    <label htmlFor="customSpeakers" className="text-sm">
                      Use custom speakers (names/roles)
                    </label>
                  </div>
                </div>
              </div>

              <div className="grid gap-4 md:grid-cols-3">
                <div className="space-y-2">
                  <Label>Realtime feel</Label>
                  <div className="flex items-center gap-2">
                    <Checkbox
                      id="simulateRealtime"
                      checked={simulateRealtime}
                      onCheckedChange={(v) => setSimulateRealtime(Boolean(v))}
                    />
                    <label htmlFor="simulateRealtime" className="text-sm">
                      Simulate realtime (reveal lines gradually)
                    </label>
                  </div>
                </div>

                <div className="space-y-2">
                  <Label>Live generation</Label>
                  <div className="flex items-center gap-2">
                    <Checkbox
                      id="useServerStreaming"
                      checked={useServerStreaming}
                      onCheckedChange={(v) => setUseServerStreaming(Boolean(v))}
                    />
                    <label htmlFor="useServerStreaming" className="text-sm">
                      Stream from server (ChatGPT-like)
                    </label>
                  </div>
                  <div className="flex items-center gap-2">
                    <Checkbox
                      id="continuousLive"
                      checked={continuousLive}
                      onCheckedChange={(v) => setContinuousLive(Boolean(v))}
                    />
                    <label htmlFor="continuousLive" className="text-sm">
                      Continuous mode (auto-continue)
                    </label>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Streams trace + lines progressively. Continuous mode automatically requests the next batch until you stop or the panel asks you a question.
                  </p>
                </div>

                <div className="space-y-2">
                  <Label>Delay per line (ms)</Label>
                  <Input
                    type="number"
                    min={40}
                    max={2000}
                    value={realtimeDelayMs}
                    onChange={(e) => setRealtimeDelayMs(Number(e.target.value) || 220)}
                    disabled={!simulateRealtime}
                  />
                  <p className="text-xs text-muted-foreground">Client-side animation only (safe + demo-friendly).</p>
                </div>
              </div>

              {useCustomSpeakers ? (
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="text-sm font-medium">Custom speakers</div>
                    <Button variant="secondary" onClick={handleAddSpeaker}>Add speaker</Button>
                  </div>

                  <div className="grid gap-3">
                    {customSpeakers.map((s, idx) => (
                      <div key={idx} className="rounded-md border p-3 space-y-3">
                        <div className="flex items-center justify-between">
                          <div className="text-sm font-medium">Speaker {idx + 1}</div>
                          <Button
                            variant="secondary"
                            onClick={() => handleRemoveSpeaker(idx)}
                            disabled={customSpeakers.length <= 2}
                          >
                            Remove
                          </Button>
                        </div>

                        <div className="grid gap-3 md:grid-cols-3">
                          <div className="space-y-2">
                            <Label>Name</Label>
                            <Input value={s.name} onChange={(e) => handleUpdateSpeaker(idx, 'name', e.target.value)} />
                          </div>
                          <div className="space-y-2">
                            <Label>Role</Label>
                            <Input value={s.role} onChange={(e) => handleUpdateSpeaker(idx, 'role', e.target.value)} placeholder="e.g., skeptic, expert, host" />
                          </div>
                          <div className="space-y-2">
                            <Label>Personality</Label>
                            <Input value={s.personality} onChange={(e) => handleUpdateSpeaker(idx, 'personality', e.target.value)} placeholder="e.g., concise, blunt, humorous" />
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </CardContent>
          </Card>

          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>1) Setup</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <FormSection
                  title="Notebook"
                  description="Pick the notebook that contains the documents you want the speakers to discuss."
                >
                  <Select value={notebookId} onValueChange={setNotebookId}>
                    <SelectTrigger>
                      <SelectValue placeholder={notebooksLoading ? 'Loading notebooks…' : 'Select a notebook'} />
                    </SelectTrigger>
                    <SelectContent>
                      {(notebooks as NotebookResponse[]).map((n) => (
                        <SelectItem key={n.id} value={n.id}>
                          {n.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {selectedNotebook ? (
                    <p className="text-xs text-muted-foreground">
                      {selectedNotebook.source_count} sources • {selectedNotebook.note_count} notes
                    </p>
                  ) : null}
                </FormSection>

                <FormSection
                  title="Episode profile"
                  description="Required: picks the default briefing + model settings. Speakers can be overridden in Live mode via “Custom speakers”."
                >
                  <Select
                    value={episodeProfileName}
                    onValueChange={(value) => setEpisodeProfileName(value)}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder={profilesLoading ? 'Loading profiles…' : 'Select an episode profile'} />
                    </SelectTrigger>
                    <SelectContent>
                      {(episodeProfiles as EpisodeProfile[]).map((p) => (
                        <SelectItem key={p.id} value={p.name}>
                          {p.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </FormSection>

                <FormSection title="Episode name" description="Used only for labeling this run.">
                  <Input
                    value={episodeName}
                    onChange={(e) => setEpisodeName(e.target.value)}
                    placeholder="e.g., 'AI agents in healthcare'"
                  />
                  {mode === 'live' && !episodeName.trim() ? (
                    <div className="pt-2">
                      <Button variant="secondary" onClick={suggestEpisodeName}>
                        Use suggested episode name
                      </Button>
                    </div>
                  ) : null}
                </FormSection>

                <FormSection
                  title="Extra instructions (optional)"
                  description="Tone, audience, things to emphasize/avoid."
                >
                  <Textarea
                    value={briefingSuffix}
                    onChange={(e) => setBriefingSuffix(e.target.value)}
                    placeholder="e.g., Keep it friendly, 10 minutes, explain jargon briefly."
                  />
                </FormSection>

                <div className="flex flex-wrap gap-3">
                  {mode === 'segmented' ? (
                    <Button
                      onClick={handleGenerateOutline}
                      disabled={!canGenerateOutline || isGeneratingOutline}
                    >
                      {isGeneratingOutline ? 'Generating outline…' : 'Generate outline'}
                    </Button>
                  ) : (
                    <Button
                      variant="secondary"
                      onClick={handleGenerateOutline}
                      disabled={!canGenerateOutline || isGeneratingOutline}
                    >
                      {isGeneratingOutline ? 'Generating outline…' : 'Generate outline (optional)'}
                    </Button>
                  )}
                  <Button variant="secondary" onClick={resetRun}>
                    Reset
                  </Button>
                </div>

                {mode === 'live' ? (
                  <p className="text-xs text-muted-foreground">
                    Use the “Ask the panel / interrupt” box on the right to start, steer, or interrupt the live discussion.
                  </p>
                ) : null}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>2) Outline</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {mode === 'live' ? (
                  <p className="text-sm text-muted-foreground">
                    Outline is optional in Live mode.
                  </p>
                ) : null}
                {!outline ? (
                  <p className="text-sm text-muted-foreground">Generate an outline to see segments.</p>
                ) : (
                  <div className="space-y-3">
                    <div className="text-sm">
                      <div className="font-medium">Speaker profile</div>
                      <div className="text-muted-foreground">{outlineResponse?.speaker_profile}</div>
                    </div>

                    <Separator />

                    <ScrollArea className="h-64 rounded-md border p-3">
                      <div className="space-y-3">
                        {outline.segments.map((s, idx) => (
                          <div key={`${s.name}-${idx}`} className="space-y-1">
                            <div className="flex items-center justify-between gap-2">
                              <div className="font-medium text-sm">
                                {idx + 1}. {s.name}
                              </div>
                              <Badge variant={sizeBadgeVariant(s.size)}>{s.size}</Badge>
                            </div>
                            <p className="text-xs text-muted-foreground">{s.description}</p>
                          </div>
                        ))}
                      </div>
                    </ScrollArea>

                    {mode !== 'live' ? (
                      <div className="flex items-center gap-2">
                        <Checkbox
                          id="askQuestions"
                          checked={askQuestions}
                          onCheckedChange={(v) => setAskQuestions(Boolean(v))}
                        />
                        <label htmlFor="askQuestions" className="text-sm">
                          Ask pause questions after each segment
                        </label>
                      </div>
                    ) : null}

                    {mode !== 'live' ? (
                      <div className="flex flex-wrap gap-3">
                        <Button
                          onClick={handleGenerateNextSegment}
                          disabled={!canGenerateSegment || isGeneratingSegment}
                        >
                          {isGeneratingSegment
                            ? 'Generating segment…'
                            : segmentIndex >= (outline?.segments.length ?? 0)
                              ? 'All segments done'
                              : `Generate segment ${segmentIndex + 1}`}
                        </Button>
                      </div>
                    ) : null}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>3) Script (multi-speaker)</CardTitle>
            </CardHeader>
            <CardContent className="space-y-5">
              <div className="grid gap-6 lg:grid-cols-2">
                <div className="space-y-3">
                  <div className="font-medium">Transcript so far</div>
                  <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                    <Badge variant="outline">Mode: {mode}</Badge>
                    <Badge variant="outline">Fact-check: {factCheckMode}</Badge>
                    <Badge variant="outline">
                      Speakers: {effectiveSpeakerNames.length ? effectiveSpeakerNames.join(', ') : 'from profile'}
                    </Badge>
                    {useCustomSpeakers ? <Badge variant="secondary">Custom speakers enabled</Badge> : null}
                  </div>
                  <ScrollArea className="h-[420px] rounded-md border p-3">
                    {transcriptSoFar.length === 0 ? (
                      <p className="text-sm text-muted-foreground">
                        {mode === 'live'
                          ? 'Click Continue to start the panel (optional: type a question to steer it).'
                          : 'Generate the first segment to start the discussion.'}
                      </p>
                    ) : (
                      <div className="space-y-3">
                        {transcriptSoFar.map((line, idx) => (
                          <div key={idx} className="space-y-1">
                            <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                              {line.speaker}
                            </div>
                            <div className="text-sm whitespace-pre-wrap">{line.dialogue}</div>
                          </div>
                        ))}
                      </div>
                    )}
                  </ScrollArea>
                </div>

                <div className="space-y-3">
                  <div className="font-medium">
                    {mode === 'live' ? 'Ask the panel / interrupt (anytime)' : 'Interrupt / steer the next segment'}
                  </div>

                  {mode === 'live' && awaitUserQuestion ? (
                    <div className="rounded-md bg-muted p-2 text-xs">
                      <div className="font-medium">Panel question</div>
                      <div className="text-muted-foreground">{awaitUserQuestion}</div>
                    </div>
                  ) : null}

                  {mode !== 'live' ? (
                    askQuestions && lastQuestions.length ? (
                      <div className="rounded-md border p-3 space-y-2">
                        <div className="text-sm font-medium">Questions from the speakers</div>
                        <ul className="list-disc pl-5 text-sm text-muted-foreground space-y-1">
                          {lastQuestions.map((q, idx) => (
                            <li key={idx}>{q}</li>
                          ))}
                        </ul>
                      </div>
                    ) : (
                      <p className="text-sm text-muted-foreground">
                        {askQuestions
                          ? 'No questions returned for the last segment.'
                          : 'Pause questions are disabled.'}
                      </p>
                    )
                  ) : null}

                  <Textarea
                    value={userInterrupt}
                    onChange={(e) => setUserInterrupt(e.target.value)}
                    placeholder={
                      mode === 'live'
                        ? "Ask the panel (e.g., 'Summarize the main claim', 'Find sources', 'Challenge this point', 'What does the notebook say about X?')"
                        : "Type your answer or an interruption (e.g., 'Focus more on risks', 'Add a skeptic voice', 'Explain this for beginners')"
                    }
                  />

                  <div className="flex flex-wrap gap-3">
                    {mode === 'live' ? (
                      <>
                        <Button onClick={handleLiveStep} disabled={isLiveStepping || !canLiveStep}>
                          {isLiveStepping ? 'Continuing…' : 'Continue (add turns)'}
                        </Button>
                        {useServerStreaming && isLiveStepping && userInterrupt.trim() ? (
                          <Button
                            variant="secondary"
                            onClick={() => {
                              pendingInterruptRef.current = true
                              setContinuousLive(false)
                              if (liveAbortRef.current) {
                                liveAbortRef.current.abort()
                              }
                            }}
                          >
                            Send now (interrupt)
                          </Button>
                        ) : null}
                        {useServerStreaming && isLiveStepping ? (
                          <Button
                            variant="secondary"
                            onClick={() => {
                              setContinuousLive(false)
                              if (liveAbortRef.current) {
                                liveAbortRef.current.abort()
                                liveAbortRef.current = null
                              }
                            }}
                          >
                            Stop
                          </Button>
                        ) : null}
                      </>
                    ) : (
                      <Button
                        onClick={handleGenerateNextSegment}
                        disabled={!canGenerateSegment || isGeneratingSegment}
                      >
                        {isGeneratingSegment
                          ? 'Continuing…'
                          : segmentIndex >= (outline?.segments.length ?? 0)
                            ? 'All segments done'
                            : 'Continue to next segment'}
                      </Button>
                    )}

                    <Button
                      variant="secondary"
                      onClick={() => setUserInterrupt('')}
                      disabled={!userInterrupt}
                    >
                      Clear
                    </Button>
                  </div>

                  <p className="text-xs text-muted-foreground">
                    Tip: Use smaller “turns per step” to interrupt mid-flow.
                  </p>

                    {mode === 'live' ? (
                      <div className="space-y-3">
                        <Separator />
                        <div className="flex items-center justify-between gap-3">
                          <div className="font-medium">Agent trace</div>
                          <Button
                            variant="secondary"
                            onClick={() => {
                              setTraceLog([])
                              setLatestEvidence(null)
                            }}
                            disabled={traceLog.length === 0 && !latestEvidence}
                          >
                            Clear trace
                          </Button>
                        </div>

                        {traceLog.length === 0 ? (
                          <p className="text-sm text-muted-foreground">
                            No trace yet. Click “Continue (add turns)” to see search steps.
                          </p>
                        ) : (
                          <ScrollArea className="h-[180px] rounded-md border p-3">
                            <div className="space-y-2">
                              {traceLog.map((e, idx) => (
                                <div key={`${e.at}-${idx}`} className="space-y-1">
                                  <div className="text-xs text-muted-foreground">
                                    {idx + 1}. <span className="font-medium">{e.step}</span>
                                    {e.provider ? ` • ${e.provider}` : ''}
                                  </div>
                                  {e.query ? (
                                    <div className="text-xs">Query: {truncateText(e.query, 140)}</div>
                                  ) : null}
                                  {typeof e.results === 'number' ? (
                                    <div className="text-xs">
                                      Results: {e.results}
                                      {e.found_nothing ? ' (found nothing)' : ''}
                                    </div>
                                  ) : null}
                                  {e.reason ? <div className="text-xs">Reason: {e.reason}</div> : null}
                                  {e.error ? <div className="text-xs text-destructive">Error: {e.error}</div> : null}
                                  {Array.isArray(e.urls) && e.urls.length ? (
                                    <div className="space-y-1">
                                      {e.urls
                                        .map((u) => safeUrl(u))
                                        .filter((u): u is string => Boolean(u))
                                        .slice(0, 5)
                                        .map((u) => (
                                          <a
                                            key={u}
                                            href={u}
                                            target="_blank"
                                            rel="noreferrer"
                                            className="block text-xs underline text-muted-foreground"
                                          >
                                            {u}
                                          </a>
                                        ))}
                                    </div>
                                  ) : null}
                                </div>
                              ))}
                            </div>
                          </ScrollArea>
                        )}

                        {latestEvidence && latestEvidence.length ? (
                          <div className="space-y-2">
                            <div className="text-sm font-medium">Latest evidence</div>
                            <ScrollArea className="h-[220px] rounded-md border p-3">
                              <div className="space-y-3">
                                {latestEvidence.slice(0, 8).map((ev, idx) => {
                                  const url = safeUrl(ev.url)
                                  const title = typeof ev.title === 'string' ? ev.title : undefined
                                  const content = ev.content ?? ev.text ?? ev.snippet
                                  return (
                                    <div key={idx} className="space-y-1">
                                      <div className="text-xs font-medium">
                                        {title || `Evidence ${idx + 1}`}
                                      </div>
                                      {url ? (
                                        <a
                                          href={url}
                                          target="_blank"
                                          rel="noreferrer"
                                          className="block text-xs underline text-muted-foreground"
                                        >
                                          {url}
                                        </a>
                                      ) : null}
                                      <div className="text-xs text-muted-foreground whitespace-pre-wrap">
                                        {truncateText(content, 240) || '(no snippet)'}
                                      </div>
                                    </div>
                                  )
                                })}
                              </div>
                            </ScrollArea>
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                </div>
              </div>

              {mode === 'live' ? (
                <div className="space-y-2">
                  <Separator />
                  <p className="text-sm text-muted-foreground">
                    Live mode generates a few turns at a time. Type your question/contradiction above and click “Continue (add turns)”.
                  </p>
                </div>
              ) : null}
            </CardContent>
          </Card>
        </div>
      </div>
    </AppShell>
  )
}
