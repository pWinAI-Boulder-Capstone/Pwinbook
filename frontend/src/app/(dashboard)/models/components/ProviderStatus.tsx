'use client'

import { useMemo } from 'react'

import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Check, X } from 'lucide-react'
import { ProviderAvailability } from '@/lib/types/models'

interface ProviderStatusProps {
  providers: ProviderAvailability
}

const VISIBLE_PROVIDERS = ['openai', 'openrouter', 'elevenlabs']

export function ProviderStatus({ providers }: ProviderStatusProps) {
  // Only show OpenAI, OpenRouter, and ElevenLabs
  const allProviders = useMemo(
    () => [
      ...providers.available
        .filter((p) => VISIBLE_PROVIDERS.includes(p))
        .map((p) => ({ name: p, available: true })),
      ...providers.unavailable
        .filter((p) => VISIBLE_PROVIDERS.includes(p))
        .map((p) => ({ name: p, available: false })),
    ],
    [providers.available, providers.unavailable],
  )

  return (
    <Card>
      <CardHeader>
        <CardTitle>AI Providers</CardTitle>
        <CardDescription>
          Configure providers through environment variables to enable their models. 
          <span className="ml-1">
            {providers.available.length} of {allProviders.length} configured
          </span>
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="grid gap-2 sm:grid-cols-2">
          {allProviders.map((provider) => {
            const supportedTypes = providers.supported_types[provider.name] ?? []

            return (
              <div
                key={provider.name}
                className={`flex items-center gap-3 rounded-lg border px-4 py-3 transition-colors ${
                  provider.available ? 'bg-card' : 'bg-muted/40'
                }`}
              >
                <div className={`flex items-center justify-center rounded-full p-1.5 ${
                  provider.available
                    ? 'bg-emerald-100 text-emerald-600 dark:bg-emerald-900/20 dark:text-emerald-300'
                    : 'bg-muted-foreground/10 text-muted-foreground'
                }`}>
                  {provider.available ? (
                    <Check className="h-3.5 w-3.5" />
                  ) : (
                    <X className="h-3.5 w-3.5" />
                  )}
                </div>

                <div className="flex min-w-0 flex-1 items-center justify-between gap-3">
                  <span
                    className={`truncate text-sm font-medium capitalize ${
                      !provider.available ? 'text-muted-foreground' : 'text-foreground'
                    }`}
                  >
                    {provider.name}
                  </span>

                  {provider.available ? (
                    <div className="flex flex-wrap items-center justify-end gap-1">
                      {supportedTypes.length > 0 ? (
                        supportedTypes.map((type) => (
                          <Badge key={type} variant="secondary" className="text-xs font-medium">
                            {type.replace('_', ' ')}
                          </Badge>
                        ))
                      ) : (
                        <Badge variant="outline" className="text-xs">No models</Badge>
                      )}
                    </div>
                  ) : (
                    <Badge variant="outline" className="text-xs text-muted-foreground border-dashed">
                      Not configured
                    </Badge>
                  )}
                </div>
              </div>
            )
          })}
        </div>


      </CardContent>
    </Card>
  )
}
