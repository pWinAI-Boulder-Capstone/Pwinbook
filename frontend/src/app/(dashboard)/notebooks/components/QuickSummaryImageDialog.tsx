'use client'

import { useState } from 'react'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Copy, Download, Image as ImageIcon, Loader2, RefreshCw } from 'lucide-react'

interface QuickSummaryImageDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  imageDataUrl?: string | null
  prompt?: string
  isGenerating: boolean
  onGenerate: () => void
}

export function QuickSummaryImageDialog({
  open,
  onOpenChange,
  imageDataUrl,
  prompt,
  isGenerating,
  onGenerate,
}: QuickSummaryImageDialogProps) {
  const [copied, setCopied] = useState(false)

  const handleDownload = () => {
    if (!imageDataUrl) return
    const now = new Date()
    const ts = now.toISOString().replace(/[:.]/g, '-')
    const filename = `quick-summary-${ts}.png`
    const link = document.createElement('a')
    link.href = imageDataUrl
    link.download = filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  const handleCopyPrompt = async () => {
    if (!prompt) return
    try {
      await navigator.clipboard.writeText(prompt)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      setCopied(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-3xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ImageIcon className="h-5 w-5" />
            Quick Summary Image
          </DialogTitle>
          <DialogDescription>
            Generate an image from your notebook quick summary.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="rounded-lg border bg-muted/20 min-h-[280px] flex items-center justify-center overflow-hidden">
            {isGenerating ? (
              <div className="flex items-center gap-2 text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                <span className="text-sm">Generating image...</span>
              </div>
            ) : imageDataUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={imageDataUrl}
                alt="Quick summary generated"
                className="max-h-[460px] w-auto object-contain"
              />
            ) : (
              <div className="text-sm text-muted-foreground text-center px-6">
                Click Generate Image to create a visual from the latest quick summary.
              </div>
            )}
          </div>

          <div className="space-y-2">
            <div className="text-xs font-medium text-muted-foreground">Prompt</div>
            <div className="rounded-md border bg-background p-3 text-xs whitespace-pre-wrap break-words max-h-40 overflow-y-auto">
              {prompt || 'No prompt yet. Generate an image first.'}
            </div>
          </div>
        </div>

        <DialogFooter className="gap-2 sm:justify-between">
          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={handleCopyPrompt}
              disabled={!prompt || isGenerating}
            >
              <Copy className="h-4 w-4 mr-2" />
              {copied ? 'Copied' : 'Copy Prompt'}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={handleDownload}
              disabled={!imageDataUrl || isGenerating}
            >
              <Download className="h-4 w-4 mr-2" />
              Download
            </Button>
          </div>

          <Button type="button" onClick={onGenerate} disabled={isGenerating}>
            {isGenerating ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                Generating...
              </>
            ) : (
              <>
                <RefreshCw className="h-4 w-4 mr-2" />
                {imageDataUrl ? 'Regenerate' : 'Generate Image'}
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
