'use client'

import { Card, CardContent } from '@/components/ui/card'
import { FileText, Book, Mic, CheckCircle2, Sparkles } from 'lucide-react'
import Link from 'next/link'
import { cn } from '@/lib/utils'

interface WelcomeGuideProps {
  hasNotebooks: boolean
  hasSources: boolean
  sourceCount: number
  notebookCount: number
}

const steps = [
  {
    number: 1,
    title: 'Add a source',
    description: 'Upload a PDF, paste a URL, or write text to build your knowledge base.',
    icon: FileText,
    href: '/sources',
    action: 'Add Source',
    key: 'sources' as const,
  },
  {
    number: 2,
    title: 'Create a notebook',
    description: 'Organize sources, take notes, and chat with your research.',
    icon: Book,
    href: '/notebooks',
    action: 'Create Notebook',
    key: 'notebooks' as const,
  },
  {
    number: 3,
    title: 'Generate a podcast',
    description: 'Turn your research into an AI-generated podcast episode.',
    icon: Mic,
    href: '/podcasts',
    action: 'Try Podcasts',
    key: 'podcasts' as const,
  },
]

export function WelcomeGuide({ hasSources, hasNotebooks, sourceCount, notebookCount }: WelcomeGuideProps) {
  const completedSteps = [hasSources, hasNotebooks, false] // podcasts never auto-complete
  const allStarted = hasSources && hasNotebooks

  if (allStarted) return null

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Sparkles className="h-4 w-4 text-primary" />
        <h2 className="text-sm font-medium text-muted-foreground">Get started</h2>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {steps.map((step, i) => {
          const done = completedSteps[i]
          return (
            <Link key={step.key} href={step.href}>
              <Card
                className={cn(
                  'relative overflow-hidden transition-all hover:border-primary/30 cursor-pointer h-full',
                  done && 'opacity-60'
                )}
              >
                <CardContent className="p-4">
                  <div className="flex items-start gap-3">
                    <div
                      className={cn(
                        'flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm font-medium',
                        done
                          ? 'bg-primary/10 text-primary'
                          : 'bg-muted text-muted-foreground'
                      )}
                    >
                      {done ? (
                        <CheckCircle2 className="h-4 w-4" />
                      ) : (
                        step.number
                      )}
                    </div>
                    <div className="min-w-0 space-y-1">
                      <p className="text-sm font-medium leading-tight">{step.title}</p>
                      <p className="text-xs text-muted-foreground leading-snug">
                        {step.description}
                      </p>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </Link>
          )
        })}
      </div>
    </div>
  )
}
