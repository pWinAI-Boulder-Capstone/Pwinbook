'use client'

import { useState, useEffect } from 'react'
import { useParams } from 'next/navigation'
import { AppShell } from '@/components/layout/AppShell'
import { NotebookHeader } from '../components/NotebookHeader'
import { SourcesColumn } from '../components/SourcesColumn'
import { NotesColumn } from '../components/NotesColumn'
import { ChatColumn } from '../components/ChatColumn'
import { useNotebook } from '@/lib/hooks/use-notebooks'
import { useSources } from '@/lib/hooks/use-sources'
import { useNotes } from '@/lib/hooks/use-notes'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { FileText, StickyNote, PanelRightClose, PanelRightOpen } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ResizableTwoPane } from '@/components/common/ResizableTwoPane'
import type {
  NoteResponse,
  NotebookResponse,
  SourceListResponse,
} from '@/lib/types/api'

export type ContextMode = 'off' | 'insights' | 'full'

export interface ContextSelections {
  sources: Record<string, ContextMode>
  notes: Record<string, ContextMode>
}

interface NotebookSourcesNotesBodyProps {
  notebook: NotebookResponse
  notebookId: string
  sources: SourceListResponse[] | undefined
  sourcesLoading: boolean
  notes: NoteResponse[] | undefined
  notesLoading: boolean
  sourceCount: number
  noteCount: number
  contextSelections: ContextSelections
  handleContextModeChange: (
    itemId: string,
    mode: ContextMode,
    type: 'source' | 'note'
  ) => void
  refetchSources: () => void
  autoOpenNoteId: string | null
  setAutoOpenNoteId: (id: string | null) => void
  chatOpen: boolean
  setChatOpen: (open: boolean) => void
}

function NotebookSourcesNotesBody({
  notebook,
  notebookId,
  sources,
  sourcesLoading,
  notes,
  notesLoading,
  sourceCount,
  noteCount,
  contextSelections,
  handleContextModeChange,
  refetchSources,
  autoOpenNoteId,
  setAutoOpenNoteId,
  chatOpen,
  setChatOpen,
}: NotebookSourcesNotesBodyProps) {
  return (
    <>
      <div className="flex-shrink-0 px-6 pt-5 pb-3">
        <NotebookHeader
          notebook={notebook}
          onQuickSummaryCreated={(noteId) => setAutoOpenNoteId(noteId)}
        />
      </div>

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <Tabs defaultValue="sources" className="flex min-h-0 flex-1 flex-col">
          <div className="flex flex-shrink-0 items-center justify-between border-b px-6">
            <TabsList className="h-10 gap-0 bg-transparent p-0">
              <TabsTrigger
                value="sources"
                className="relative h-10 rounded-none border-b-2 border-transparent px-4 data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none gap-2"
              >
                <FileText className="h-3.5 w-3.5" />
                Sources
                {sourceCount > 0 && (
                  <Badge variant="secondary" className="h-5 px-1.5 text-[10px]">
                    {sourceCount}
                  </Badge>
                )}
              </TabsTrigger>
              <TabsTrigger
                value="notes"
                className="relative h-10 rounded-none border-b-2 border-transparent px-4 data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none gap-2"
              >
                <StickyNote className="h-3.5 w-3.5" />
                Notes
                {noteCount > 0 && (
                  <Badge variant="secondary" className="h-5 px-1.5 text-[10px]">
                    {noteCount}
                  </Badge>
                )}
              </TabsTrigger>
            </TabsList>

            <Button
              variant="ghost"
              size="sm"
              onClick={() => setChatOpen(!chatOpen)}
              className="h-8 gap-2 text-muted-foreground"
            >
              {chatOpen ? (
                <>
                  <PanelRightClose className="h-3.5 w-3.5" />
                  <span className="hidden text-xs sm:inline">Hide Chat</span>
                </>
              ) : (
                <>
                  <PanelRightOpen className="h-3.5 w-3.5" />
                  <span className="hidden text-xs sm:inline">Show Chat</span>
                </>
              )}
            </Button>
          </div>

          <TabsContent value="sources" className="mt-0 flex-1 overflow-y-auto p-6">
            <SourcesColumn
              sources={sources}
              isLoading={sourcesLoading}
              notebookId={notebookId}
              notebookName={notebook.name}
              onRefresh={refetchSources}
              contextSelections={contextSelections.sources}
              onContextModeChange={(sourceId, mode) =>
                handleContextModeChange(sourceId, mode, 'source')
              }
            />
          </TabsContent>

          <TabsContent value="notes" className="mt-0 flex-1 overflow-y-auto p-6">
            <NotesColumn
              notes={notes}
              isLoading={notesLoading}
              notebookId={notebookId}
              contextSelections={contextSelections.notes}
              onContextModeChange={(noteId, mode) =>
                handleContextModeChange(noteId, mode, 'note')
              }
              autoOpenNoteId={autoOpenNoteId ?? undefined}
              onAutoOpenHandled={() => setAutoOpenNoteId(null)}
            />
          </TabsContent>
        </Tabs>
      </div>
    </>
  )
}

export default function NotebookPage() {
  const params = useParams()
  const notebookId = decodeURIComponent(params.id as string)

  const { data: notebook, isLoading: notebookLoading } = useNotebook(notebookId)
  const { data: sources, isLoading: sourcesLoading, refetch: refetchSources } = useSources(notebookId)
  const { data: notes, isLoading: notesLoading } = useNotes(notebookId)
  const [autoOpenNoteId, setAutoOpenNoteId] = useState<string | null>(null)
  const [chatOpen, setChatOpen] = useState(true)

  // Context selection state
  const [contextSelections, setContextSelections] = useState<ContextSelections>({
    sources: {},
    notes: {}
  })

  // Initialize default context selections when sources load
  useEffect(() => {
    if (sources && sources.length > 0) {
      setContextSelections(prev => {
        const newSourceSelections = { ...prev.sources }
        sources.forEach(source => {
          if (!(source.id in newSourceSelections)) {
            newSourceSelections[source.id] = source.insights_count > 0 ? 'insights' : 'full'
          }
        })
        return { ...prev, sources: newSourceSelections }
      })
    }
  }, [sources])

  // Initialize default context selections when notes load
  useEffect(() => {
    if (notes && notes.length > 0) {
      setContextSelections(prev => {
        const newNoteSelections = { ...prev.notes }
        notes.forEach(note => {
          if (!(note.id in newNoteSelections)) {
            newNoteSelections[note.id] = 'full'
          }
        })
        return { ...prev, notes: newNoteSelections }
      })
    }
  }, [notes])

  const handleContextModeChange = (itemId: string, mode: ContextMode, type: 'source' | 'note') => {
    setContextSelections(prev => ({
      ...prev,
      [type === 'source' ? 'sources' : 'notes']: {
        ...(type === 'source' ? prev.sources : prev.notes),
        [itemId]: mode
      }
    }))
  }

  if (notebookLoading) {
    return (
      <AppShell>
        <div className="flex-1 flex items-center justify-center">
          <LoadingSpinner size="lg" />
        </div>
      </AppShell>
    )
  }

  if (!notebook) {
    return (
      <AppShell>
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center">
            <h1 className="text-xl font-semibold mb-2">Notebook not found</h1>
            <p className="text-sm text-muted-foreground">The requested notebook could not be found.</p>
          </div>
        </div>
      </AppShell>
    )
  }

  const sourceCount = sources?.length ?? 0
  const noteCount = notes?.length ?? 0

  return (
    <AppShell>
      <div className="flex flex-1 min-h-0 overflow-hidden">
        {!chatOpen ? (
          <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden border-r">
            <NotebookSourcesNotesBody
              notebook={notebook}
              notebookId={notebookId}
              sources={sources}
              sourcesLoading={sourcesLoading}
              notes={notes}
              notesLoading={notesLoading}
              sourceCount={sourceCount}
              noteCount={noteCount}
              contextSelections={contextSelections}
              handleContextModeChange={handleContextModeChange}
              refetchSources={refetchSources}
              autoOpenNoteId={autoOpenNoteId}
              setAutoOpenNoteId={setAutoOpenNoteId}
              chatOpen={chatOpen}
              setChatOpen={setChatOpen}
            />
          </div>
        ) : (
          <ResizableTwoPane
            storageKey="open-notebook:split:notebook-chat"
            defaultLeftPercent={52}
            primary={
              <div className="flex h-full min-h-0 flex-col overflow-hidden">
                <NotebookSourcesNotesBody
                  notebook={notebook}
                  notebookId={notebookId}
                  sources={sources}
                  sourcesLoading={sourcesLoading}
                  notes={notes}
                  notesLoading={notesLoading}
                  sourceCount={sourceCount}
                  noteCount={noteCount}
                  contextSelections={contextSelections}
                  handleContextModeChange={handleContextModeChange}
                  refetchSources={refetchSources}
                  autoOpenNoteId={autoOpenNoteId}
                  setAutoOpenNoteId={setAutoOpenNoteId}
                  chatOpen={chatOpen}
                  setChatOpen={setChatOpen}
                />
              </div>
            }
            secondary={
              <div className="flex h-full min-h-0 flex-col overflow-hidden">
                <ChatColumn
                  notebookId={notebookId}
                  contextSelections={contextSelections}
                />
              </div>
            }
          />
        )}
      </div>
    </AppShell>
  )
}
