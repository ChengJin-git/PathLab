import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Loader2, Sparkles, Undo2 } from 'lucide-react'
import { polishResearchGoal } from '../../api/autoresearch'
import type { SupportedLanguage } from '../../i18n'
import { useResearchText } from './researchText'
import { Button } from '../ui/button'

interface ResearchGoalEditorProps {
  value: string
  onChange: (value: string) => void
  sourceConversationId?: string
  disabled: boolean
  onPolishingChange: (polishing: boolean) => void
}

export default function ResearchGoalEditor({
  value,
  onChange,
  sourceConversationId,
  disabled,
  onPolishingChange
}: ResearchGoalEditorProps) {
  const { i18n } = useTranslation()
  const { text } = useResearchText()
  const language = i18n.resolvedLanguage as SupportedLanguage
  const [polishing, setPolishing] = useState(false)
  const [original, setOriginal] = useState<string>()
  const [notice, setNotice] = useState<'done' | 'failed' | 'stale'>()
  const request = useRef<AbortController>()
  const current = useRef({ value, sourceConversationId, language })
  current.current = { value, sourceConversationId, language }

  useEffect(() => () => request.current?.abort(), [])

  async function polish() {
    if (request.current || disabled || !value.trim()) return
    const controller = new AbortController()
    request.current = controller
    const input = current.current
    setPolishing(true)
    onPolishingChange(true)
    setNotice(undefined)
    try {
      const result = await polishResearchGoal(
        {
          question: input.value.trim(),
          language: input.language,
          source_conversation_id: input.sourceConversationId
        },
        controller.signal
      )
      if (controller.signal.aborted) return
      const latest = current.current
      if (
        latest.value !== input.value ||
        latest.sourceConversationId !== input.sourceConversationId ||
        latest.language !== input.language
      ) {
        setNotice('stale')
        return
      }
      setOriginal(input.value)
      onChange(result.question)
      setNotice('done')
    } catch {
      if (!controller.signal.aborted) setNotice('failed')
    } finally {
      if (!controller.signal.aborted) {
        request.current = undefined
        setPolishing(false)
        onPolishingChange(false)
      }
    }
  }

  return (
    <section className="rounded-2xl border border-gray-200 bg-white p-6">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <label
          htmlFor="research-goal"
          className="text-sm font-semibold text-gray-900"
        >
          {text.goal}
        </label>
        <div className="flex items-center gap-2">
          {original !== undefined && (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={disabled || polishing}
              onClick={() => {
                onChange(original)
                setOriginal(undefined)
                setNotice(undefined)
              }}
              className="gap-1.5"
            >
              <Undo2 size={13} />
              {text.undoPolish}
            </Button>
          )}
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => void polish()}
            disabled={
              disabled || polishing || !value.trim() || value.length > 12000
            }
            title={text.polishHint}
            className="gap-1.5"
          >
            {polishing ? (
              <Loader2 size={13} className="animate-spin" />
            ) : (
              <Sparkles size={13} />
            )}
            {polishing ? text.polishing : text.polish}
          </Button>
        </div>
      </div>
      <textarea
        id="research-goal"
        value={value}
        onChange={(event) => {
          onChange(event.target.value)
          setOriginal(undefined)
          setNotice(undefined)
        }}
        disabled={disabled}
        maxLength={12000}
        placeholder={text.placeholder}
        className="min-h-40 w-full resize-y rounded-xl border border-gray-200 bg-gray-50/50 p-4 text-sm leading-7 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
        required
      />
      {notice && (
        <p
          role={notice === 'failed' ? 'alert' : 'status'}
          className={`mt-2 text-xs leading-6 ${notice === 'failed' ? 'text-red-700' : 'text-gray-500'}`}
        >
          {notice === 'done'
            ? text.polishDone
            : notice === 'stale'
              ? text.polishStale
              : text.polishFailed}
        </p>
      )}
    </section>
  )
}
