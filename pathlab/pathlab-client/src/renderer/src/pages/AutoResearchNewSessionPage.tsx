import { FormEvent, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { Label } from '../components/ui/label'
import { startAutoResearchSession } from '../api/autoresearch'
import { notifyAutoResearchSessionCreated } from '../lib/autoresearchSessionEvents'

const DEFAULT_MODEL = 'gpt-5.5'
const DEFAULT_MAX_ITER = 5
const MIN_MAX_ITER = 1
const MAX_MAX_ITER = 20

function parseMaxIter(value: string): number {
  const parsed = Number.parseInt(value, 10)
  if (!Number.isFinite(parsed)) return DEFAULT_MAX_ITER
  return Math.min(MAX_MAX_ITER, Math.max(MIN_MAX_ITER, parsed))
}

export default function AutoResearchNewSessionPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [question, setQuestion] = useState('')
  const [maxIterInput, setMaxIterInput] = useState(String(DEFAULT_MAX_ITER))
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    if (!question.trim()) return
    setIsSubmitting(true)
    setError('')
    try {
      const session = await startAutoResearchSession({
        question: question.trim(),
        max_iter: parseMaxIter(maxIterInput),
        model: DEFAULT_MODEL,
      })
      notifyAutoResearchSessionCreated(session)
      navigate(`/autoresearch/sessions/${session.session_id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('autoResearch.newSessionPage.startFailed'))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="flex h-full flex-col">
      <section className="flex flex-1 flex-col rounded-3xl border border-gray-200 bg-white p-6 shadow-sm sm:p-8">
        <div className="mb-6">
          <h1 className="text-3xl font-extrabold tracking-tight text-gray-950">{t('autoResearch.newSessionPage.title')}</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-gray-500">
            {t('autoResearch.newSessionPage.description')}
          </p>
        </div>

        <form className="flex flex-1 flex-col space-y-5" onSubmit={handleSubmit}>
          <div className="space-y-2">
            <Label htmlFor="question" className="text-gray-700">{t('autoResearch.newSessionPage.researchQuestion')}</Label>
            <div className="relative flex-1 rounded-2xl border border-gray-200 bg-white shadow-sm transition focus-within:border-blue-300 focus-within:ring-4 focus-within:ring-blue-100">
              <textarea
                id="question"
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                className="h-full min-h-36 w-full resize-none rounded-2xl bg-transparent px-4 py-3 text-sm leading-6 text-gray-900 outline-none placeholder:text-gray-400"
                placeholder={t('autoResearch.newSessionPage.questionPlaceholder')}
              />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="maxIter" className="text-gray-700">{t('autoResearch.newSessionPage.maxIter')}</Label>
            <div className="flex items-center gap-4">
              <Input
                id="maxIter"
                type="number"
                min={MIN_MAX_ITER}
                max={MAX_MAX_ITER}
                value={maxIterInput}
                onChange={(event) => setMaxIterInput(event.target.value)}
                onBlur={() => setMaxIterInput(String(parseMaxIter(maxIterInput)))}
                className="w-24 border-gray-200 bg-white text-gray-900 shadow-sm focus-visible:ring-blue-200"
              />
              <span className="text-sm text-gray-400">
                {t('autoResearch.newSessionPage.maxIterHint', { min: MIN_MAX_ITER, max: MAX_MAX_ITER })}
              </span>
            </div>
          </div>

          <div className="flex-1" />

          {error && <div className="rounded-2xl border border-red-200 bg-red-50 p-3 text-sm font-medium text-red-700">{error}</div>}

          <div className="flex flex-col-reverse gap-3 pt-2 sm:flex-row sm:justify-end">
            <Button type="button" variant="outline" className="border-gray-200 bg-white text-gray-700 hover:bg-gray-50" onClick={() => navigate('/dashboard')}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" disabled={isSubmitting || !question.trim()} className="bg-blue-600 text-white shadow-sm hover:bg-blue-700">
              {isSubmitting ? t('autoResearch.newSessionPage.starting') : t('autoResearch.newSessionPage.startSession')}
            </Button>
          </div>
        </form>
      </section>
    </div>
  )
}
