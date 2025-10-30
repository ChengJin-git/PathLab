import { API_BASE } from './config'

/**
 * Fetch WSI list from database via Gateway API
 */
export async function fetchWSIList() {
  const res = await fetch(`${API_BASE}/wsi`)
  if (!res.ok) {
    throw new Error('Failed to load WSI list from database')
  }
  return res.json()
}

/**
 * Fetch WSI detail from database via Gateway API
 */
export async function fetchWSIDetail(wsi_id: string) {
  const res = await fetch(`${API_BASE}/wsi/${encodeURIComponent(wsi_id)}`)
  if (!res.ok) {
    throw new Error('Failed to get WSI detail from database')
  }
  return res.json()
}

/**
 * Compute patch coordinates for a WSI using PrePATH/CLAM-style tissue segmentation
 * Uses settings from localStorage if not provided
 */
export async function computePatches(
  wsi_id: string,
  options?: {
    patch_size?: number
    stride?: number
    level?: number
    force_recompute?: boolean
    // Segmentation parameters
    sthresh?: number
    mthresh?: number
    close?: number
    use_otsu?: boolean
    contour_fn?: string
  }
) {
  // Get settings from localStorage
  const patch_size = options?.patch_size ?? parseInt(localStorage.getItem('patch_size') || '512')
  const stride = options?.stride ?? parseInt(localStorage.getItem('patch_stride') || '512')
  const level = options?.level ?? parseInt(localStorage.getItem('patch_level') || '0')
  const sthresh = options?.sthresh ?? parseInt(localStorage.getItem('seg_sthresh') || '20')
  const mthresh = options?.mthresh ?? parseInt(localStorage.getItem('seg_mthresh') || '7')
  const close = options?.close ?? parseInt(localStorage.getItem('seg_close') || '4')
  const use_otsu = options?.use_otsu ?? (localStorage.getItem('seg_use_otsu') === 'true')
  const contour_fn = options?.contour_fn ?? (localStorage.getItem('seg_contour_fn') || 'four_pt')
  const force_recompute = options?.force_recompute ?? false

  // Build query parameters
  const params = new URLSearchParams({
    patch_size: String(patch_size),
    stride: String(stride),
    level: String(level),
    force_recompute: String(force_recompute),
    sthresh: String(sthresh),
    mthresh: String(mthresh),
    close: String(close),
    use_otsu: String(use_otsu),
    contour_fn: contour_fn
  })

  const res = await fetch(`${API_BASE}/wsi/${encodeURIComponent(wsi_id)}/compute_patches?${params}`, {
    method: 'POST'
  })

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to compute patches: ${errorText}`)
  }

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
    age?: number
    gender?: string
    source?: string
    wsi_id?: string
    onProgress?: (progress: number) => void
  }
) {
  /**
   * Upload a WSI file to the server.
   *
   * @param file - The WSI file to upload
   * @param options - Optional metadata (label, case_id, age, gender, source, wsi_id) and progress callback
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
  if (options?.age !== undefined) {
    formData.append('age', options.age.toString())
  }
  if (options?.gender) {
    formData.append('gender', options.gender)
  }
  if (options?.source) {
    formData.append('source', options.source)
  }
  if (options?.wsi_id) {
    formData.append('wsi_id', options.wsi_id)
  }

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()

    // Track upload progress
    xhr.upload.addEventListener('progress', (e) => {
      if (e.lengthComputable && options?.onProgress) {
        const progress = Math.round((e.loaded / e.total) * 100)
        options.onProgress(progress)
      }
    })

    // Handle completion
    xhr.addEventListener('load', () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const result = JSON.parse(xhr.responseText)
          resolve(result)
        } catch (err) {
          reject(new Error('Failed to parse response'))
        }
      } else {
        reject(new Error(`Failed to upload WSI file: ${xhr.responseText}`))
      }
    })

    // Handle errors
    xhr.addEventListener('error', () => {
      reject(new Error('Network error during upload'))
    })

    xhr.addEventListener('abort', () => {
      reject(new Error('Upload aborted'))
    })

    // Send request
    xhr.open('POST', `${API_BASE}/wsi/upload/file`)
    xhr.send(formData)
  })
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

export async function downloadCSVTemplate() {
  /**
   * Download CSV template for batch WSI upload.
   */
  const res = await fetch(`${API_BASE}/wsi/upload/csv/template`)
  if (!res.ok) {
    throw new Error('Failed to download CSV template')
  }

  // Get the blob and create a download link
  const blob = await res.blob()
  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'wsi_upload_template.csv'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  window.URL.revokeObjectURL(url)
}

export async function deleteWSI(wsi_id: string) {
  /**
   * Delete a WSI and its associated data.
   *
   * @param wsi_id - The WSI ID to delete
   * @returns Delete result
   */
  const res = await fetch(`${API_BASE}/wsi/${wsi_id}`, {
    method: 'DELETE'
  })

  if (!res.ok) {
    const error = await res.json()
    throw new Error(error.detail || 'Failed to delete WSI')
  }

  return await res.json()
}

export async function updateWSIMetadata(
  wsi_id: string,
  metadata: {
    label?: string
    case_id?: string
    age?: number
    gender?: string
    source?: string
  }
) {
  /**
   * Update WSI metadata (label, case_id, age, gender, source).
   *
   * @param wsi_id - The WSI ID to update
   * @param metadata - Metadata to update
   * @returns Update result
   */
  const params = new URLSearchParams()
  if (metadata.label !== undefined) {
    params.append('label', metadata.label)
  }
  if (metadata.case_id !== undefined) {
    params.append('case_id', metadata.case_id)
  }
  if (metadata.age !== undefined) {
    params.append('age', metadata.age.toString())
  }
  if (metadata.gender !== undefined) {
    params.append('gender', metadata.gender)
  }
  if (metadata.source !== undefined) {
    params.append('source', metadata.source)
  }

  const res = await fetch(`${API_BASE}/wsi/${wsi_id}?${params.toString()}`, {
    method: 'PATCH'
  })

  if (!res.ok) {
    const error = await res.json()
    throw new Error(error.detail || 'Failed to update WSI metadata')
  }

  return await res.json()
}

export async function uploadWSIByCSV(file: File) {
  /**
   * Batch register WSI files by uploading a CSV file.
   *
   * CSV format (with header):
   * wsi_path,label,case_id,wsi_id
   * /path/to/slide1.svs,HSIL,case_001,slide_001
   * /path/to/slide2.svs,LSIL,case_002,slide_002
   *
   * @param file - CSV file containing WSI paths and metadata
   * @returns Batch upload result with success/failed counts
   */
  const formData = new FormData()
  formData.append('file', file)

  const res = await fetch(`${API_BASE}/wsi/upload/csv`, {
    method: 'POST',
    body: formData
  })

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to upload CSV: ${errorText}`)
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
  // Get AI configuration from localStorage
  const apiKey = localStorage.getItem('siliconflow_api_key') || ''
  const baseUrl = localStorage.getItem('siliconflow_base_url') || 'https://api.siliconflow.cn/v1'
  const model = localStorage.getItem('siliconflow_model') || 'Qwen/Qwen3-VL-235B-A22B-Instruct'

  const res = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-SiliconFlow-API-Key': apiKey,
      'X-SiliconFlow-Base-URL': baseUrl,
      'X-SiliconFlow-Model': model
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
  // Get AI configuration from localStorage
  const apiKey = localStorage.getItem('siliconflow_api_key') || ''
  const baseUrl = localStorage.getItem('siliconflow_base_url') || 'https://api.siliconflow.cn/v1'
  const model = localStorage.getItem('siliconflow_model') || 'Qwen/Qwen3-VL-235B-A22B-Instruct'

  const res = await fetch(`${API_BASE}/parse-task`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-SiliconFlow-API-Key': apiKey,
      'X-SiliconFlow-Base-URL': baseUrl,
      'X-SiliconFlow-Model': model
    },
    body: JSON.stringify({ description })
  })

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to parse task: ${errorText}`)
  }

  return res.json()
}

/**
 * Get all training tasks
 * @returns List of training tasks
 */
export async function getTrainingTasks() {
  const res = await fetch(`${API_BASE}/tasks/training`)

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to get training tasks: ${errorText}`)
  }

  const data = await res.json()
  return data.items || []
}

/**
 * Get training task by ID
 * @param taskId - Training task ID
 * @returns Training task details
 */
export async function getTrainingTask(taskId: string) {
  const res = await fetch(`${API_BASE}/tasks/training/${taskId}`)

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to get training task: ${errorText}`)
  }

  return res.json()
}

/**
 * Delete training task
 * @param taskId - Training task ID
 */
export async function deleteTrainingTask(taskId: string) {
  const res = await fetch(`${API_BASE}/tasks/training/${taskId}`, {
    method: 'DELETE'
  })

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to delete training task: ${errorText}`)
  }

  return res.json()
}

/**
 * Create a custom training task
 * @param taskConfig - Training task configuration
 * @returns Task creation result with task_id
 */
export async function createTrainingTask(taskConfig: {
  task_name: string
  task_type: 'classification' | 'segmentation'
  task_description: string
  wsi_ids: string[]
  preprocessing: {
    tile_size: number
    stride: number
    feature_extractor: string
    feature_batch_size: number
    use_gpu: boolean
    // Tissue segmentation parameters
    sthresh?: number
    mthresh?: number
    close?: number
    use_otsu?: boolean
    contour_fn?: string
    use_padding?: boolean
  }
  model: {
    aggregator: string
    learning_rate: number
    epochs: number
    optimizer: string
    batch_size: number
  }
}) {
  const res = await fetch(`${API_BASE}/tasks/training`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(taskConfig)
  })

  if (!res.ok) {
    const errorText = await res.text()
    throw new Error(`Failed to create training task: ${errorText}`)
  }

  return res.json()
}
