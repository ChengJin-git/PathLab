import { API_BASE } from './config'

// Embedded CSV data as fallback
const EMBEDDED_CSV = `wsi_id,label,case_id,wsi_path
slide_001,HSIL,case_001,/home/peter/code/project/demo/uploads/50365e2349564e8588f79f1d1a00ef93.tif
slide_002,LSIL,case_002,/home/peter/code/project/demo/uploads/7777b8bd718c43afbae016efe7cd1525.tif`

// Parse CSV data
function parseCSV(text: string) {
  const lines = text.trim().split('\n')
  if (lines.length < 2) return []

  const headers = lines[0].split(',').map(h => h.trim())
  const items = []

  for (let i = 1; i < lines.length; i++) {
    const values = lines[i].split(',').map(v => v.trim())
    const item: any = {}
    headers.forEach((header, idx) => {
      item[header] = values[idx] || ''
    })
    items.push(item)
  }

  return items
}

export async function fetchWSIList() {
  // Vite serves files from public directory at the base path
  const res = await fetch(`${import.meta.env.BASE_URL}source.csv`)
  if (!res.ok) throw new Error('Failed to load CSV')
  const text = await res.text()
  const items = parseCSV(text)
  return { items }
}

export async function fetchWSIDetail(wsi_id: string) {
  // Try to get from CSV first
  try {
    const listData = await fetchWSIList()
    const item = listData.items.find((it: any) => it.wsi_id === wsi_id)
    if (item) {
      return {
        wsi_id: item.wsi_id,
        meta: {
          label: item.label,
          case_id: item.case_id,
          wsi_path: item.wsi_path
        }
      }
    }
  } catch (err) {
    console.error('Failed to get detail from CSV:', err)
  }

  // Fallback to API
  const res = await fetch(`${API_BASE}/wsi/${encodeURIComponent(wsi_id)}`)
  if (!res.ok) throw new Error('Failed to get WSI detail')
  return res.json()
}

export async function analyzeWSI(wsi_id: string, params: any = {}) {
  /**
   * Call Gateway to create a WSI classification task.
   * Gateway will orchestrate the request to AI Service.
   */
  console.log('Analyzing WSI:', wsi_id, 'with params:', params)

  const res = await fetch(`${API_BASE}/tasks/wsi-classification`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      wsi_id,
      params
    })
  })

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to analyze WSI: ${errorText}`)
  }

  return res.json()
}

export async function fetchResults(wsi_id: string) {
  /**
   * Fetch AI analysis results from Gateway.
   * Gateway will get the latest results from AI Service or local cache.
   */
  try {
    const res = await fetch(`${API_BASE}/results/${encodeURIComponent(wsi_id)}`)
    if (!res.ok) {
      throw new Error('Failed to get results')
    }
    const result = await res.json()

    // Return null if no prediction available
    if (!result.pred) {
      return null
    }

    return result
  } catch (err) {
    console.error('Failed to fetch results:', err)
    return null
  }
}

export async function uploadWSIFile(
  file: File,
  options?: {
    label?: string
    case_id?: string
    wsi_id?: string
  }
) {
  /**
   * Upload a WSI file to the server.
   *
   * @param file - The WSI file to upload
   * @param options - Optional metadata (label, case_id, wsi_id)
   * @returns Upload result with wsi_id and metadata
   */
  const formData = new FormData()
  formData.append('file', file)

  if (options?.label) {
    formData.append('label', options.label)
  }
  if (options?.case_id) {
    formData.append('case_id', options.case_id)
  }
  if (options?.wsi_id) {
    formData.append('wsi_id', options.wsi_id)
  }

  const res = await fetch(`${API_BASE}/wsi/upload/file`, {
    method: 'POST',
    body: formData
  })

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to upload WSI file: ${errorText}`)
  }

  return res.json()
}

export async function uploadWSIByPath(
  wsi_path: string,
  options?: {
    label?: string
    case_id?: string
    wsi_id?: string
  }
) {
  /**
   * Register a WSI by file path (without copying the file).
   *
   * @param wsi_path - Path to the WSI file on the server
   * @param options - Optional metadata (label, case_id, wsi_id)
   * @returns Upload result with wsi_id and metadata
   */
  const res = await fetch(`${API_BASE}/wsi/upload/path`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      wsi_path,
      label: options?.label,
      case_id: options?.case_id,
      wsi_id: options?.wsi_id
    })
  })

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to register WSI by path: ${errorText}`)
  }

  return res.json()
}

export async function fetchStats() {
  /**
   * Fetch system statistics from Gateway.
   * Returns WSI count, task count, completed count, results count, and label distribution.
   */
  try {
    const res = await fetch(`${API_BASE}/stats`)
    if (!res.ok) {
      throw new Error('Failed to get stats')
    }
    return res.json()
  } catch (err) {
    console.error('Failed to fetch stats:', err)
    return {
      wsi_count: 0,
      task_count: 0,
      completed_count: 0,
      results_count: 0,
      labels: {}
    }
  }
}

/**
 * Chat with AI assistant (streaming)
 * @param messages - Array of chat messages
 * @param onChunk - Callback for each chunk of response
 * @returns Promise that resolves when streaming is complete
 */
export async function chatWithAI(
  messages: Array<{ role: 'user' | 'assistant', content: string }>,
  onChunk: (chunk: string) => void
): Promise<void> {
  const res = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ messages })
  })

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to chat with AI: ${errorText}`)
  }

  // Handle streaming response
  const reader = res.body?.getReader()
  if (!reader) {
    throw new Error('Response body is not readable')
  }

  const decoder = new TextDecoder()

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      const chunk = decoder.decode(value, { stream: true })
      const lines = chunk.split('\n')

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6)
          if (data === '[DONE]') {
            return
          }
          try {
            const parsed = JSON.parse(data)
            if (parsed.content) {
              onChunk(parsed.content)
            }
          } catch (e) {
            // Skip invalid JSON
          }
        }
      }
    }
  } finally {
    reader.releaseLock()
  }
}

/**
 * Parse task description using LLM
 * @param description - Natural language task description
 * @returns Parsed task parameters
 */
export async function parseTaskDescription(description: string) {
  const res = await fetch(`${API_BASE}/parse-task`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ description })
  })

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to parse task: ${errorText}`)
  }

  return res.json()
}
