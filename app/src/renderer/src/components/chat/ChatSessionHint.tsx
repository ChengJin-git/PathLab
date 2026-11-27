import { useMemo, useState } from 'react'
import { MessageSquarePlus, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'

export function isLongConversation(messages: { role: string; content: string }[]): boolean {
  let turns = 0, characters = 0
  for (const message of messages) {
    if (message.role !== 'user' && message.role !== 'assistant') continue
    turns += 1
    characters += message.content.length
    if (turns >= 24 || characters >= 24000) return true
  }
  return false
}

export default function ChatSessionHint({ messages, generating, onNewSession, conversationId }: {
  messages: { role: string; content: string }[]; generating: boolean; onNewSession: () => void; conversationId?: string
}) {
  const { i18n } = useTranslation()
  const dismissalKey = `chat:length-hint-dismissed:${conversationId || 'new'}`
  const [dismissed, setDismissed] = useState(() => {
    try { return sessionStorage.getItem(dismissalKey) === '1' } catch { return false }
  })
  const dismiss = () => {
    setDismissed(true)
    try { sessionStorage.setItem(dismissalKey, '1') } catch { /* Keep the in-memory choice. */ }
  }
  const long = useMemo(() => isLongConversation(messages), [messages])
  if (!long || dismissed || generating) return null
  const zh = i18n.language.startsWith('zh'), hk = /zh-(HK|TW|Hant)/i.test(i18n.language)
  return <aside role="status" className="my-4 scroll-mb-72 flex items-start gap-3 rounded-xl border border-blue-100 bg-blue-50/60 p-4">
    <MessageSquarePlus size={19} className="mt-0.5 shrink-0 text-blue-600" /><div className="flex-1"><p className="text-sm font-medium text-gray-800">{zh ? (hk ? '對話越來越長了，要開啟新會話嗎？' : '对话越来越长了，要开启新会话吗？') : 'The chat is getting longer. Start a new session?'}</p><p className="mt-1 text-xs leading-5 text-gray-500">{zh ? (hk ? '新會話能讓重點更清晰。您也可以繼續在這裡聊天，記錄會保留。' : '新会话能让重点更清晰。您也可以继续在这里聊天，记录会保留。') : 'A fresh session can help keep things focused. You can also keep chatting here; your history stays saved.'}</p><button onClick={onNewSession} className="mt-2 cursor-pointer text-xs font-semibold text-blue-700 hover:underline">{zh ? (hk ? '開啟新會話' : '开启新会话') : 'Start a new session'}</button></div><button onClick={dismiss} aria-label={zh ? (hk ? '繼續目前對話' : '继续当前对话') : 'Keep this conversation'} className="cursor-pointer rounded p-1 text-gray-500 hover:bg-blue-100"><X size={15} /></button>
  </aside>
}
