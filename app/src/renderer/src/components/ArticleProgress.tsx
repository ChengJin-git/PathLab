import { Check, Circle, Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { ArticleGeneration } from '../api/reports'

export default function ArticleProgress({
  generation,
}: {
  generation: ArticleGeneration
}) {
  const { t } = useTranslation()
  const stages = ['evidence', 'literature', 'writing', 'review']
  const index =
    generation.stage === 'completed' ? 4 : stages.indexOf(generation.stage)
  const active = ['running', 'queued'].includes(generation.status)
  const count = generation.completed_sections.length
  return (
    <section
      className="rounded-xl border border-blue-100 bg-blue-50/40 p-4 sm:p-5"
      aria-label={t('reports.generationProgress')}
    >
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-gray-900">
          {t(`reports.state_${generation.status}`)}
        </h2>
        <span className="text-xs text-gray-600">
          {count} / {Math.max(0, generation.total_sections - 1)}{' '}
          {t('reports.sections')} · {generation.reference_count}{' '}
          {t('reports.references')}
        </span>
      </div>
      <ol className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {stages.map((stage, i) => (
          <li
            key={stage}
            className={`flex items-center gap-2 text-xs ${i <= index ? 'text-blue-800' : 'text-gray-500'}`}
          >
            <span
              className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${i < index ? 'bg-blue-600 text-white' : 'border bg-white'}`}
            >
              {i < index ? (
                <Check size={14} />
              ) : i === index && active ? (
                <Loader2
                  size={14}
                  className="animate-spin motion-reduce:animate-none"
                />
              ) : (
                <Circle size={10} />
              )}
            </span>
            {t(`reports.stage_${stage}`)}
          </li>
        ))}
      </ol>
      <p role="status" className="mt-4 text-xs leading-5 text-gray-600">
        {generation.current_section && active
          ? `${t('reports.writingSection')} ${generation.current_section}`
          : t(
              active
                ? 'reports.backgroundHint'
                : generation.status === 'completed'
                  ? 'reports.articleReady'
                  : `reports.failure_${generation.error_code || 'generation_failed'}`,
              { defaultValue: t('reports.failure_generation_failed') },
            )}
      </p>
    </section>
  )
}
