import { API_BASE } from '../config'
import { apiFetch, withAuthTokenQuery } from './client'

// =============================================================================
// Types
// =============================================================================

export type DownloadSourceType = 'huggingface' | 'kaggle' | 'geo' | 'zenodo' | 'url'

export interface DatasetDownloadRequest {
  source_type: DownloadSourceType
  identifier: string
  token?: string
  subset?: string
  file_patterns?: string[]
  kaggle_username?: string
  kaggle_key?: string
}

export interface DownloadedFile {
  filename: string
  size: number
  path: string
}

export interface DownloadProgress {
  downloaded_bytes: number
  total_bytes: number
  speed: number
  current_file: string
  files_done: number
  files_total: number
}

export interface DownloadTaskInfo {
  task_id: string
  source_type: DownloadSourceType
  identifier: string
  status: 'pending' | 'downloading' | 'completed' | 'failed' | 'cancelled'
  progress: DownloadProgress
  files: DownloadedFile[]
  total_size: number
  error: string | null
  created_at?: string
}

// =============================================================================
// API Functions
// =============================================================================

export async function startDatasetDownload(
  req: DatasetDownloadRequest
): Promise<{ task_id: string; message: string }> {
  return apiFetch(`${API_BASE}/datasets/download`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  }, 'Failed to start dataset download')
}

export function streamDownloadProgress(
  taskId: string,
  onData: (data: DownloadTaskInfo) => void,
  onError?: (error: string) => void,
  onDone?: () => void,
): () => void {
  const url = withAuthTokenQuery(`${API_BASE}/datasets/download/${taskId}/stream`)
  const eventSource = new EventSource(url)

  eventSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data) as DownloadTaskInfo
      onData(data)

      // Close when terminal
      if (data.status === 'completed' || data.status === 'failed' || data.status === 'cancelled') {
        eventSource.close()
        onDone?.()
      }
    } catch (e) {
      console.error('Failed to parse SSE data:', e)
    }
  }

  eventSource.onerror = () => {
    onError?.('Connection lost')
    eventSource.close()
    onDone?.()
  }

  return () => eventSource.close()
}

export async function cancelDownload(taskId: string): Promise<void> {
  await apiFetch(`${API_BASE}/datasets/download/${taskId}`, {
    method: 'DELETE',
  }, 'Failed to cancel download')
}

export async function listDownloads(): Promise<{ items: DownloadTaskInfo[] }> {
  return apiFetch(`${API_BASE}/datasets/download/list`, undefined, 'Failed to list downloads')
}
