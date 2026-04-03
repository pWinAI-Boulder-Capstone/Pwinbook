'use client'

import { useRouter, useParams } from 'next/navigation'
import { useCallback } from 'react'
import { Button } from '@/components/ui/button'
import { ArrowLeft } from 'lucide-react'
import { useSourceChat } from '@/lib/hooks/useSourceChat'
import { ChatPanel } from '@/components/source/ChatPanel'
import { useNavigation } from '@/lib/hooks/use-navigation'
import { SourceDetailContent } from '@/components/source/SourceDetailContent'
import { ResizableTwoPane } from '@/components/common/ResizableTwoPane'

export default function SourceDetailPage() {
  const router = useRouter()
  const params = useParams()
  const sourceId = decodeURIComponent(params.id as string)
  const navigation = useNavigation()

  // Initialize source chat
  const chat = useSourceChat(sourceId)

  const handleBack = useCallback(() => {
    const returnPath = navigation.getReturnPath()
    router.push(returnPath)
    navigation.clearReturnTo()
  }, [navigation, router])

  return (
    <div className="flex flex-col h-screen">
      {/* Back button */}
      <div className="pt-6 pb-4 px-6">
        <Button
          variant="ghost"
          size="sm"
          onClick={handleBack}
          className="mb-4"
        >
          <ArrowLeft className="mr-2 h-4 w-4" />
          {navigation.getReturnLabel()}
        </Button>
      </div>

      {/* Main content: Source detail + Chat (draggable split) */}
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden px-6 pb-6">
        <ResizableTwoPane
          storageKey="open-notebook:split:source-chat"
          defaultLeftPercent={62}
          primary={
            <div className="min-h-0 overflow-y-auto px-4 pt-2">
              <SourceDetailContent
                sourceId={sourceId}
                showChatButton={false}
                onClose={handleBack}
              />
            </div>
          }
          secondary={
            <div className="min-h-0 overflow-y-auto px-4 pt-2">
              <ChatPanel
                messages={chat.messages}
                isStreaming={chat.isStreaming}
                contextIndicators={chat.contextIndicators}
                onSendMessage={(message, model, maxImages) =>
                  chat.sendMessage(message, model, maxImages)
                }
                modelOverride={chat.currentSession?.model_override}
                onModelChange={(model) => {
                  if (chat.currentSessionId) {
                    chat.updateSession(chat.currentSessionId, { model_override: model })
                  }
                }}
                sessions={chat.sessions}
                currentSessionId={chat.currentSessionId}
                onCreateSession={(title) => chat.createSession({ title })}
                onSelectSession={chat.switchSession}
                onUpdateSession={(sessionId, title) =>
                  chat.updateSession(sessionId, { title })
                }
                onDeleteSession={chat.deleteSession}
                loadingSessions={chat.loadingSessions}
              />
            </div>
          }
        />
      </div>
    </div>
  )
}
