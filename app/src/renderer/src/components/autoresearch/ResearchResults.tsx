import ReactECharts from '../charts/LazyECharts'
import type {
  AutoResearchEvent,
  ResearchExperiment,
  ResearchJob
} from '../../types/autoresearch'
import { useResearchText } from './researchText'

export function ExperimentComparison({
  experiments
}: {
  experiments: ResearchExperiment[]
}) {
  const { text } = useResearchText()
  const completed = experiments.filter((run) => run.status === 'completed')
  const keys = [
    ...new Set(completed.flatMap((run) => Object.keys(run.metrics || {})))
  ].filter(
    (key) =>
      /auc|accuracy|f1|c_index|dice|iou|loss/i.test(key) &&
      !key.startsWith('train')
  )
  const metrics = keys
    .sort((a, b) => Number(b.startsWith('test')) - Number(a.startsWith('test')))
    .slice(0, 8)
  if (!completed.length || !metrics.length) return null
  const chartMetric =
    metrics.find((key) => /auc|accuracy|dice|c_index/i.test(key)) || metrics[0]
  return (
    <section className="space-y-4" aria-label={text.result}>
      <ReactECharts
        style={{ height: 210 }}
        option={{
          animation: false,
          grid: { left: 45, right: 15, top: 32, bottom: 45 },
          title: {
            text: chartMetric,
            textStyle: { fontSize: 12, fontWeight: 500, color: '#475569' }
          },
          tooltip: { trigger: 'axis' },
          xAxis: {
            type: 'category',
            data: completed.map((run) => `#${run.iteration}`),
            axisTick: { show: false }
          },
          yAxis: {
            type: 'value',
            scale: true,
            splitLine: { lineStyle: { color: '#f1f5f9' } }
          },
          series: [
            {
              type: 'bar',
              barMaxWidth: 42,
              itemStyle: { color: '#2563eb', borderRadius: [4, 4, 0, 0] },
              data: completed.map((run) => run.metrics[chartMetric] ?? null)
            }
          ]
        }}
      />
      <div className="overflow-x-auto rounded-2xl border border-[color:var(--surface-border)]">
        <table className="w-full text-left text-xs">
          <thead className="bg-gray-50 text-gray-500">
            <tr>
              <th className="p-3">{text.name}</th>
              {metrics.map((key) => (
                <th className="whitespace-nowrap p-3" key={key}>
                  {key}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {completed.map((run) => (
              <tr key={run.run_id} className="border-t border-[color:var(--surface-border)]">
                <th
                  className="max-w-48 truncate p-3 font-medium"
                  title={run.experiment_name}
                >
                  {run.experiment_name}
                </th>
                {metrics.map((key) => (
                  <td key={key} className="p-3 font-mono">
                    {typeof run.metrics[key] === 'number'
                      ? run.metrics[key].toFixed(4)
                      : '—'}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

export function JobProgress({
  job,
  events
}: {
  job: ResearchJob
  events: AutoResearchEvent[]
}) {
  const { text, status } = useResearchText()
  if (job.status === 'queued' && job.payload.device === 'gpu') {
    return <div role="status" className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-6 text-amber-900">
      <p className="font-medium">{text.gpuWaiting}</p>
      <p>{text.gpuWaitingHint}</p>
      {job.scheduling && <p>{text.gpuQueuePosition}: {job.scheduling.position} · {text.gpuMemoryRequired}: {(job.scheduling.required_vram_mb / 1024).toFixed(1)} GiB</p>}
    </div>
  }
  const updates = events.filter(
    (event) => event.job_id === job.job_id || event.run_id === job.job_id
  )
  const progressEvent = [...updates]
    .reverse()
    .find(
      (event) => event.kind === 'progress' || event.kind === 'download_progress'
    )
  const progress = (progressEvent?.progress || {}) as Record<string, unknown>
  const current = Number(
    progress.current_epoch ?? progress.epoch ?? progress.downloaded_bytes ?? 0
  )
  const total = Number(
    progress.total_epochs ?? progress.epochs ?? progress.bytes_total ?? 0
  )
  const percent =
    total > 0 ? Math.min(100, Math.max(0, (current / total) * 100)) : null
  if (!progressEvent) return null
  return (
    <div className="mt-3 space-y-2 text-xs text-gray-600">
      <div className="flex justify-between gap-2">
        <span>
          {job.kind === 'download'
            ? text.downloadProgress
            : text.experimentProgress}
        </span>
        <span>
          {job.status === 'completed'
            ? text.completed
            : percent !== null
              ? `${percent.toFixed(0)}%`
              : status(job.status)}
        </span>
      </div>
      {percent !== null && (
        <progress
          max={100}
          value={percent}
          aria-label={
            job.kind === 'download'
              ? text.downloadProgress
              : text.experimentProgress
          }
          className="h-1.5 w-full accent-blue-600"
        />
      )}
      <div className="flex flex-wrap gap-x-3 gap-y-1">
        {Object.entries(progress)
          .filter(([, value]) => ['number', 'string'].includes(typeof value))
          .slice(0, 8)
          .map(([key, value]) => (
            <span key={key}>
              {key}: {String(value)}
            </span>
          ))}
      </div>
    </div>
  )
}
