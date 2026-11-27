import {
  CheckCircle2,
  CircleAlert,
  Loader2,
  Download,
  FlaskConical,
} from 'lucide-react'
import type { AutoResearchEvent, ResearchJob } from '../../types/autoresearch'
import { useResearchText } from './researchText'

export default function ResearchJobNotice({
  event,
  job,
  onLogs,
}: {
  event: AutoResearchEvent
  job?: ResearchJob
  onLogs: (path: string) => void
}) {
  const { text, status } = useResearchText()
  const result = job?.result || ((event.result || {}) as ResearchJob['result'])
  const state = job?.status || event.status || 'queued'
  const failed = ['failed', 'cancelled'].includes(state)
  const done = state === 'completed'
  const download = (job?.kind || event.job_kind) === 'download'
  const computation = (job?.kind || event.job_kind) === 'computation'
  const registration = result.registration
  const Icon = done ? CheckCircle2 : failed ? CircleAlert : Loader2
  return (
    <article
      className={`rounded-xl border p-4 ${failed ? 'border-amber-200 bg-amber-50/50' : 'border-gray-200 bg-white'}`}
    >
      <div className="flex items-start gap-3">
        {download ? (
          <Download size={18} className="mt-0.5 text-blue-600" />
        ) : (
          <FlaskConical size={18} className="mt-0.5 text-blue-600" />
        )}
        <div className="min-w-0 flex-1">
          <h3 className="break-words text-sm font-medium leading-6 text-gray-900">
            {String(
              job?.payload.name ||
                (download ? text.publicData : text.experiment),
            )}
          </h3>
          <span
            className={`mt-1 inline-flex items-center gap-1.5 text-xs ${done ? 'text-emerald-700' : failed ? 'text-amber-800' : 'text-blue-700'}`}
          >
            <Icon
              size={13}
              className={!done && !failed ? 'animate-spin' : ''}
            />
            {status(state)}
          </span>
        </div>
      </div>
      {failed && (
        <p className="mt-3 text-sm leading-6 text-gray-700">
          {text.jobIncomplete}
        </p>
      )}
      {done && (
        <p className="mt-3 text-sm leading-6 text-gray-600">
          {download
            ? text.downloadFinished
            : computation
              ? text.analysisFinished
              : text.computationFinished}
        </p>
      )}
      {done && download && registration && (
        <div className="mt-2 text-xs leading-6 text-gray-600">
          <p>
            {String(registration.dataset_name || '')} ·{' '}
            {registration.is_public ? text.datasetPublic : text.datasetPrivate}{' '}
            · {String(registration.source_organ || text.metadataUnknown)}
          </p>
          {registration.metadata_complete === false && (
            <p className="text-amber-700">
              {text.metadataIncomplete}:{' '}
              {((registration.missing_metadata as string[]) || [])
                .map(
                  (field) =>
                    ({
                      organs: text.datasetOrgan,
                      license: text.datasetLicense,
                      source_url: text.datasetSource,
                    })[field] || field,
                )
                .join('、')}
            </p>
          )}
          {registration.training_ready === false && (
            <p>{text.datasetNotReady}</p>
          )}
        </div>
      )}
      {!!result.metrics && (
        <div className="mt-3 grid grid-cols-2 gap-2">
          {Object.entries(result.metrics)
            .slice(0, 4)
            .map(([key, value]) => (
              <div key={key} className="rounded-lg bg-gray-50 p-2">
                <span className="block break-words text-[11px] text-gray-500">
                  {key}
                </span>
                <strong className="font-mono text-sm font-medium text-gray-800">
                  {typeof value === 'number'
                    ? Number(value.toPrecision(5))
                    : String(value)}
                </strong>
              </div>
            ))}
        </div>
      )}
      {result.log_path && (
        <button
          onClick={() => onLogs(result.log_path!)}
          className="mt-3 cursor-pointer text-xs font-medium text-blue-700 hover:underline"
        >
          {text.logs}
        </button>
      )}
      <details className="mt-3 text-xs text-gray-500">
        <summary className="cursor-pointer">{text.rawLog}</summary>
        <pre className="mt-2 max-h-52 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-gray-50 p-3 font-mono text-[11px] leading-5">
          {JSON.stringify(result, null, 2)}
        </pre>
      </details>
    </article>
  )
}
