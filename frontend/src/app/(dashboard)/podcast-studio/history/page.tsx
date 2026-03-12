'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { AppShell } from '@/components/layout/AppShell'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { useToast } from '@/lib/hooks/use-toast'
import { listStudioSessions, deleteStudioSession, getStudioSessionExportUrl } from '@/lib/api/studio-sessions'
import type { StudioSessionListResponse } from '@/lib/types/studio-sessions'
import { formatDistanceToNow } from 'date-fns'

function statusVariant(status: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (status === 'completed') return 'default'
  if (status === 'error') return 'destructive'
  if (status === 'stopped') return 'secondary'
  return 'outline'
}

function formatBadge(text: string): 'default' | 'secondary' | 'outline' | 'destructive' {
  if (text === 'both') return 'default'
  if (text === 'internet') return 'secondary'
  if (text === 'notebook') return 'outline'
  return 'default'
}

export default function StudioSessionsHistoryPage() {
  const router = useRouter()
  const { toast } = useToast()
  const [sessions, setSessions] = useState<StudioSessionListResponse>([])
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')

  const loadSessions = async () => {
    try {
      setLoading(true)
      const data = await listStudioSessions({
        search: searchQuery || undefined,
        limit: 100,
      })
      setSessions(data)
    } catch {
      toast({
        title: 'Failed to load sessions',
        description: 'Please try again later',
        variant: 'destructive',
      })
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadSessions()
  }, [])

  const handleDelete = async (sessionId: string) => {
    if (!confirm('Are you sure you want to delete this session?')) return

    try {
      await deleteStudioSession(sessionId)
      toast({ title: 'Session deleted' })
      loadSessions()
    } catch {
      toast({
        title: 'Failed to delete',
        description: 'Please try again',
        variant: 'destructive',
      })
    }
  }

  const handleExport = (sessionId: string, format: 'txt' | 'md' | 'json') => {
    const url = getStudioSessionExportUrl(sessionId, format)
    window.open(url, '_blank')
  }

  return (
    <AppShell>
      <div className="flex flex-col gap-4 p-4">
        {/* Header */}
        <div className="flex justify-between items-center mb-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Session History</h1>
            <p className="text-muted-foreground">
              View and manage your past podcast studio sessions
            </p>
          </div>
          <Button variant="outline" onClick={() => router.push('/podcast-studio')}>
            Back to Studio
          </Button>
        </div>

        {/* Filters */}
        <div className="flex gap-2">
          <Input
            placeholder="Search by briefing..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="max-w-sm"
          />
          <Button variant="outline" onClick={loadSessions}>
            Search
          </Button>
        </div>

        {/* Sessions List */}
        <ScrollArea className="h-[600px]">
          <div className="flex flex-col gap-2">
            {loading ? (
              <div className="text-center py-8 text-muted-foreground">Loading...</div>
            ) : sessions.length === 0 ? (
              <div className="text-center py-8 text-muted-foreground">
                No sessions found. Start a new session to see it here.
              </div>
            ) : (
              sessions.map((session) => (
                <Card key={session.session_id}>
                  <CardHeader className="pb-2">
                    <div className="flex justify-between items-start">
                      <div>
                        <CardTitle className="text-lg">{session.briefing}</CardTitle>
                        <div className="flex gap-2 mt-1">
                          <Badge variant={statusVariant(session.status)}>{session.status}</Badge>
                          <Badge variant="outline">{session.turn_count} turns</Badge>
                          <Badge variant={formatBadge(session.fact_check_mode)}>
                            Fact check: {session.fact_check_mode}
                          </Badge>
                        </div>
                      </div>
                      <div className="text-sm text-muted-foreground">
                        {formatDistanceToNow(new Date(session.created_at), { addSuffix: true })}
                      </div>
                    </div>
                  </CardHeader>
                  <CardContent>
                    <Separator className="my-2" />
                    <div className="flex justify-between items-center">
                      <div className="text-sm text-muted-foreground">
                        Speakers: {session.speakers.map(s => s.name).join(', ')}
                      </div>
                      <div className="flex gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => handleExport(session.session_id, 'txt')}
                        >
                          TXT
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => handleExport(session.session_id, 'md')}
                        >
                          MD
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => handleExport(session.session_id, 'json')}
                        >
                          JSON
                        </Button>
                        <Button
                          variant="destructive"
                          size="sm"
                          onClick={() => handleDelete(session.session_id)}
                        >
                          Delete
                        </Button>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))
            )}
          </div>
        </ScrollArea>
      </div>
    </AppShell>
  )
}
