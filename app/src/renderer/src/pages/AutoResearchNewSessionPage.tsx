import { FormEvent, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { dataTypeLabel } from '../lib/dataTypeLabel'
import { useNavigate, useSearchParams, useLocation } from 'react-router-dom'
import {
  ArrowRight,
  Database,
  Loader2,
  Search,
  FlaskConical
} from 'lucide-react'
import {
  getResearchConfiguration,
  getResearchHandoff,
  getResearchDatasets,
  startAutoResearchSession
} from '../api/autoresearch'
import { notifyAutoResearchSessionCreated } from '../lib/autoresearchSessionEvents'
import { useResearchText } from '../components/autoresearch/researchText'
import ResearchGoalEditor from '../components/autoresearch/ResearchGoalEditor'
import ResearchAdvancedSettings from '../components/autoresearch/ResearchAdvancedSettings'
import { Checkbox } from '../components/ui/checkbox'
import { Button } from '../components/ui/button'
import { SegmentedControl } from '../components/ui/workspace-primitives'
import type { AdvancedResearchSettings, ResearchDataset, ResearchEffort } from '../types/autoresearch'

export default function AutoResearchNewSessionPage() {
  const { t } = useTranslation()
  const { text, language } = useResearchText()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const location = useLocation()
  const handoff = location.state as {
    researchGoal?: string
    datasetIds?: string[]
    sourceConversationId?: string
  } | null
  const [chatContext, setChatContext] =
    useState<Awaited<ReturnType<typeof getResearchHandoff>>>()
  const [includeChat, setIncludeChat] = useState(true)
  const [question, setQuestion] = useState(
    handoff?.researchGoal || params.get('question') || ''
  )
  const [selected, setSelected] = useState<string[]>(
    handoff?.datasetIds || params.getAll('dataset_id')
  )
  const [datasets, setDatasets] = useState<ResearchDataset[]>([])
  const [query, setQuery] = useState('')
  const [configuration, setConfiguration] =
    useState<Awaited<ReturnType<typeof getResearchConfiguration>>>()
  const [effort, setEffort] = useState<ResearchEffort>('medium')
  const [advanced, setAdvanced] = useState<AdvancedResearchSettings>({})
  const [importingSkill, setImportingSkill] = useState(false)
  const [downloads, setDownloads] = useState(true)
  const [busy, setBusy] = useState(false)
  const [polishing, setPolishing] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    if (!handoff?.sourceConversationId) return
    let active = true
    getResearchHandoff(handoff.sourceConversationId)
      .then((value) => {
        if (active) setChatContext(value)
      })
      .catch((e) => {
        if (active) setError(String(e))
      })
    return () => {
      active = false
    }
  }, [handoff?.sourceConversationId])

  useEffect(() => {
    let live = true
    getResearchConfiguration()
      .then((value) => {
        if (live) setConfiguration(value)
      })
      .catch((e) => {
        if (live) setError(String(e))
      })
    return () => {
      live = false
    }
  }, [])
  useEffect(() => {
    let live = true
    const timer = setTimeout(
      () =>
        getResearchDatasets(query, params.get('workspace_id') || undefined)
          .then((value) => {
            if (live) setDatasets(value.items)
          })
          .catch((e) => {
            if (live) setError(String(e))
          }),
      200
    )
    return () => {
      live = false
      clearTimeout(timer)
    }
  }, [query])

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (busy || polishing || importingSkill || !question.trim()) return
    setBusy(true)
    setError('')
    try {
      const session = await startAutoResearchSession({
        question: question.trim(),
        language,
        dataset_ids: selected,
        workspace_id:
          chatContext?.workspace_id || params.get('workspace_id') || undefined,
        source_conversation_id: includeChat
          ? handoff?.sourceConversationId
          : undefined,
        effort,
        advanced,
        allow_downloads: downloads
      })
      notifyAutoResearchSessionCreated(session)
      navigate(`/autoresearch/sessions/${session.session_id}`)
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e)
      const code = message.match(/\bskill[A-Z][A-Za-z]+\b/)?.[0] || message
      setError(text[code as keyof typeof text] || message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto w-full max-w-5xl py-6">
      {handoff?.sourceConversationId && (
        <section className="mb-5 rounded-xl border border-blue-100 bg-blue-50/50 p-4 text-sm text-gray-700">
          <div className="flex items-center gap-2 font-medium">
            <Checkbox
              id="research-chat-context"
              checked={includeChat}
              onCheckedChange={setIncludeChat}
              disabled={busy}
            />
            <label htmlFor="research-chat-context" className="cursor-pointer">
              {text.inheritChat}
            </label>
          </div>
          <p className="mt-2 text-xs leading-6 text-gray-600">
            {text.inheritChatHint}
          </p>
          {chatContext && (
            <details className="mt-3 text-xs">
              <summary className="cursor-pointer text-blue-700">
                {text.contextPreview} · {chatContext.included_messages}/
                {chatContext.message_count}
              </summary>
              <div className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-white p-3 text-sm leading-7">
                {chatContext.context}
              </div>
            </details>
          )}
        </section>
      )}
      <div className="mb-8 flex items-start gap-4">
        <div className="rounded-xl bg-blue-50 p-3 text-blue-700">
          <FlaskConical size={24} />
        </div>
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-gray-950">
            {text.newResearch}
          </h1>
          <p className="mt-2 text-sm leading-6 text-gray-600">
            {text.subtitle}
          </p>
        </div>
      </div>
      <form onSubmit={submit} className="space-y-6">
        <ResearchGoalEditor
          value={question}
          onChange={setQuestion}
          sourceConversationId={
            includeChat ? handoff?.sourceConversationId : undefined
          }
          disabled={busy}
          onPolishingChange={setPolishing}
        />
        <section className="rounded-2xl border border-gray-200 bg-white p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="flex items-center gap-2 text-sm font-semibold">
              <Database size={17} />
              {text.data}{' '}
              <span className="font-normal text-gray-500">
                {selected.length} {text.selected}
              </span>
            </h2>
            <div className="flex items-center gap-2 rounded-lg border px-3 py-2">
              <Search size={15} className="text-gray-400" />
              <input
                aria-label={text.search}
                placeholder={text.search}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="w-44 bg-transparent text-sm outline-none"
              />
            </div>
          </div>
          <p className="mt-2 text-xs leading-5 text-gray-500">
            {text.dataHint}
          </p>
          <div className="mt-4 grid max-h-72 gap-2 overflow-y-auto sm:grid-cols-2">
            {datasets.map((dataset) => (
              <div
                key={dataset.dataset_id}
                className={`flex cursor-pointer items-center gap-3 rounded-xl border p-3 transition-colors ${selected.includes(dataset.dataset_id) ? 'border-blue-300 bg-blue-50' : 'border-gray-200 hover:bg-gray-50'}`}
              >
                <Checkbox
                  id={`research-dataset-${dataset.dataset_id}`}
                  checked={selected.includes(dataset.dataset_id)}
                  onCheckedChange={(checked) =>
                    setSelected((current) =>
                      checked
                        ? [...current, dataset.dataset_id]
                        : current.filter((id) => id !== dataset.dataset_id)
                    )
                  }
                  disabled={busy}
                />
                <label
                  htmlFor={`research-dataset-${dataset.dataset_id}`}
                  className="min-w-0 flex-1 cursor-pointer"
                >
                  <span className="block truncate text-sm font-medium text-gray-900">
                    {dataset.name}
                  </span>
                  <span className="text-xs text-gray-500">
                    {dataTypeLabel(t, dataset.data_type)} ·{' '}
                    {dataset.file_count.toLocaleString()} {text.files}
                  </span>
                </label>
              </div>
            ))}
          </div>
        </section>
        <section className="space-y-5 rounded-2xl border border-gray-200 bg-white p-6">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <h2 className="text-sm font-semibold text-gray-900">
              {text.effort}
            </h2>
            <SegmentedControl<ResearchEffort>
              aria-label={text.effort}
              value={effort}
              onChange={next => { setEffort(next); setAdvanced(current => ({ skills: current.skills })) }}
              disabled={busy}
              options={[
                { value: 'low', label: text.effortLow },
                { value: 'medium', label: text.effortMedium },
                { value: 'high', label: text.effortHigh }
              ]}
            />
          </div>
          <p className="text-xs leading-6 text-gray-500">
            {
              {
                low: text.effortLowHint,
                medium: text.effortMediumHint,
                high: text.effortHighHint
              }[effort]
            }
          </p>
          <ResearchAdvancedSettings
            value={advanced}
            defaults={configuration?.effort_presets.standard[effort]}
            onChange={setAdvanced}
            disabled={busy}
            onImportingChange={setImportingSkill}
          />
          <div className="flex items-center gap-3 border-t border-gray-100 pt-4 text-sm text-gray-700">
            <Checkbox
              id="research-public-data"
              checked={downloads}
              onCheckedChange={setDownloads}
              disabled={busy}
            />
            <label htmlFor="research-public-data" className="cursor-pointer">
              {text.downloads}
            </label>
          </div>
        </section>
        {(error || configuration?.error) && (
          <p
            role="alert"
            className="rounded-xl bg-red-50 p-4 text-sm text-red-700"
          >
            {error || configuration?.error}
          </p>
        )}
        <div className="flex justify-end">
          <Button
            type="submit"
            size="lg"
            disabled={
              busy ||
              polishing ||
              importingSkill ||
              !question.trim() ||
              !configuration?.can_execute ||
              !!configuration?.error
            }
            className="gap-2"
          >
            {busy ? (
              <Loader2 size={17} className="animate-spin" />
            ) : (
              <ArrowRight size={17} />
            )}
            {busy ? text.starting : text.start}
          </Button>
        </div>
      </form>
    </div>
  )
}
