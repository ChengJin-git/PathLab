import { useQuery } from '@tanstack/react-query'
import { resultGet, type AnalysisRun, type Page } from '../../api/resultWorkbench'
import type { BackgroundTask, TaskStatus } from './types'

export function useWorkbenchAnalyses(enabled: boolean, audienceKey: string) {
  const query = useQuery({
    queryKey: ['workbench-background', audienceKey],
    queryFn: ({ signal }) => resultGet<Page<AnalysisRun>>('/runs', { limit: 20, status: 'background' }, signal),
    enabled,
    refetchInterval: query => query.state.data?.items.some(run => ['queued', 'running', 'cancelling'].includes(run.status)) ? 2000 : 15000,
    refetchIntervalInBackground: true,
  })
  return enabled ? (query.data?.items || []).map((run): BackgroundTask => {
    const status: TaskStatus = run.status === 'completed' ? 'success' : run.status === 'failed' ? 'error' : run.status === 'cancelled' ? 'cancelled' : run.status === 'queued' ? 'pending' : 'running'
    return {
      id: `workbench_${run.analysis_id}`, workbenchAnalysisId: run.analysis_id,
      type: 'analysis', title: run.title, taskName: run.title, status,
      items: [{ id: run.analysis_id, name: run.title, status, progress: run.progress, error: run.error || undefined }],
      totalProgress: run.progress, createdAt: new Date(run.created_at),
      completedAt: run.finished_at ? new Date(run.finished_at) : undefined,
      successCount: status === 'success' ? 1 : 0, failedCount: status === 'error' ? 1 : 0,
      isServerTask: true,
    }
  }) : []
}
