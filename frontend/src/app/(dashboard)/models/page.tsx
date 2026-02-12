'use client'

import { AppShell } from '@/components/layout/AppShell'
import { ProviderStatus } from './components/ProviderStatus'
import { ModelTypeSection } from './components/ModelTypeSection'
import { DefaultModelsSection } from './components/DefaultModelsSection'
import { useModels, useModelDefaults, useProviders } from '@/lib/hooks/use-models'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'

export default function ModelsPage() {
  const { data: models, isLoading: modelsLoading, refetch: refetchModels } = useModels()
  const { data: defaults, isLoading: defaultsLoading, refetch: refetchDefaults } = useModelDefaults()
  const { data: providers, isLoading: providersLoading, refetch: refetchProviders } = useProviders()

  const handleRefresh = () => {
    refetchModels()
    refetchDefaults()
    refetchProviders()
  }

  if (modelsLoading || defaultsLoading || providersLoading) {
    return (
      <AppShell>
        <div className="flex items-center justify-center min-h-[60vh]">
          <LoadingSpinner size="lg" />
        </div>
      </AppShell>
    )
  }

  if (!models || !defaults || !providers) {
    return (
      <AppShell>
        <div className="p-6">
          <div className="text-center py-12">
            <p className="text-muted-foreground">Failed to load models data</p>
          </div>
        </div>
      </AppShell>
    )
  }

  return (
    <AppShell>
      <div className="flex-1 overflow-y-auto">
        <div className="p-6 space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-xl font-semibold">Models</h1>
              <p className="text-sm text-muted-foreground mt-1">
                Configure AI models for different purposes
              </p>
            </div>
            <Button variant="ghost" size="icon" className="h-8 w-8" onClick={handleRefresh}>
              <RefreshCw className="h-3.5 w-3.5" />
            </Button>
        </div>

        <div className="grid gap-6">
          {/* Provider Status */}
          <ProviderStatus providers={providers} />

          {/* Default Models */}
          <DefaultModelsSection models={models} defaults={defaults} />

          {/* Model Types */}
          <div className="grid gap-6 lg:grid-cols-2">
            <ModelTypeSection 
              type="language" 
              models={models} 
              providers={providers}
              isLoading={modelsLoading}
            />
            <ModelTypeSection 
              type="embedding" 
              models={models} 
              providers={providers}
              isLoading={modelsLoading}
            />
            <ModelTypeSection 
              type="text_to_speech" 
              models={models} 
              providers={providers}
              isLoading={modelsLoading}
            />
            <ModelTypeSection 
              type="speech_to_text" 
              models={models} 
              providers={providers}
              isLoading={modelsLoading}
            />
          </div>
        </div>
        </div>
      </div>
    </AppShell>
  )
}
