'use client'

import { useMemo, useState } from 'react'

import { AppShell } from '@/components/layout/AppShell'
import { NotebookList } from './components/NotebookList'
import { Button } from '@/components/ui/button'
import { Plus, RefreshCw } from 'lucide-react'
import { useNotebooks } from '@/lib/hooks/use-notebooks'
import { CreateNotebookDialog } from '@/components/notebooks/CreateNotebookDialog'
import { Input } from '@/components/ui/input'
import { WelcomeGuide } from '@/components/common/WelcomeGuide'

export default function NotebooksPage() {
  const [createDialogOpen, setCreateDialogOpen] = useState(false)
  const [searchTerm, setSearchTerm] = useState('')
  const { data: notebooks, isLoading, refetch } = useNotebooks(false)
  const { data: archivedNotebooks } = useNotebooks(true)

  const normalizedQuery = searchTerm.trim().toLowerCase()

  const filteredActive = useMemo(() => {
    if (!notebooks) return undefined
    if (!normalizedQuery) return notebooks
    return notebooks.filter((notebook) =>
      notebook.name.toLowerCase().includes(normalizedQuery)
    )
  }, [notebooks, normalizedQuery])

  const filteredArchived = useMemo(() => {
    if (!archivedNotebooks) return undefined
    if (!normalizedQuery) return archivedNotebooks
    return archivedNotebooks.filter((notebook) =>
      notebook.name.toLowerCase().includes(normalizedQuery)
    )
  }, [archivedNotebooks, normalizedQuery])

  const hasArchived = (archivedNotebooks?.length ?? 0) > 0
  const isSearching = normalizedQuery.length > 0
  const notebookCount = notebooks?.length ?? 0
  const hasNotebooks = notebookCount > 0
  // We approximate hasSources — if any notebook has sources, the user has started
  const hasSources = notebooks?.some(n => n.source_count > 0) ?? false

  return (
    <AppShell>
      <div className="flex-1 overflow-y-auto">
        <div className="p-6 space-y-6">
          {/* Welcome guide for new users — disappears once they have notebooks + sources */}
          {!isLoading && (
            <WelcomeGuide
              hasNotebooks={hasNotebooks}
              hasSources={hasSources}
              sourceCount={0}
              notebookCount={notebookCount}
            />
          )}

          {/* Page header */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <h1 className="text-xl font-semibold">Notebooks</h1>
              <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => refetch()}>
                <RefreshCw className="h-3.5 w-3.5" />
              </Button>
            </div>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-3">
              {hasNotebooks && (
                <Input
                  value={searchTerm}
                  onChange={(event) => setSearchTerm(event.target.value)}
                  placeholder="Search notebooks…"
                  className="w-full sm:w-56 h-9"
                />
              )}
              <Button size="sm" onClick={() => setCreateDialogOpen(true)}>
                <Plus className="h-4 w-4 mr-1.5" />
                New Notebook
              </Button>
            </div>
          </div>
        
          <div className="space-y-8">
            <NotebookList 
              notebooks={filteredActive} 
              isLoading={isLoading}
              title="Active Notebooks"
              emptyTitle={isSearching ? 'No notebooks match your search' : undefined}
              emptyDescription={isSearching ? 'Try using a different notebook name.' : undefined}
            />
            
            {hasArchived && (
              <NotebookList 
                notebooks={filteredArchived} 
                isLoading={false}
                title="Archived Notebooks"
                collapsible
                emptyTitle={isSearching ? 'No archived notebooks match your search' : undefined}
                emptyDescription={isSearching ? 'Modify your search to find archived notebooks.' : undefined}
              />
            )}
          </div>
        </div>
      </div>

      <CreateNotebookDialog
        open={createDialogOpen}
        onOpenChange={setCreateDialogOpen}
      />
    </AppShell>
  )
}
