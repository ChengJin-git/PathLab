import { useState } from 'react'
import { getResearchRunMetrics } from '../../api/autoresearch'
import type { ResearchExperiment } from '../../types/autoresearch'

/** Config and metrics of one run. The JSON is rendered only while open, and the full
 * metrics are fetched on first open when the session payload carried a preview. */
export function RunDetails({ sessionId, run, label }: { sessionId: string; run: ResearchExperiment; label: string }) {
  const [open, setOpen] = useState(false)
  const [metrics, setMetrics] = useState<Record<string, number> | null>(null)
  const preview = (run.metrics_total ?? 0) > Object.keys(run.metrics || {}).length
  return (
    <details
      className="mt-3 text-xs"
      onToggle={(event) => {
        const next = event.currentTarget.open
        setOpen(next)
        if (next && preview && !metrics)
          void getResearchRunMetrics(sessionId, run.run_id)
            .then((value) => setMetrics(value.metrics))
            .catch(() => undefined)
      }}
    >
      <summary className="cursor-pointer text-gray-500">{label}</summary>
      {open && (
        <pre className="mt-2 max-h-48 overflow-auto">
          {JSON.stringify({ config: run.config, metrics: metrics || run.metrics }, null, 2)}
        </pre>
      )}
    </details>
  )
}
