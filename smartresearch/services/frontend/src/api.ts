import { API_BASE, AI_BASE } from './config'

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
  // Placeholder: simulate AI analysis
  console.log('Analyzing WSI:', wsi_id, 'with params:', params)

  // Simulate delay
  await new Promise(resolve => setTimeout(resolve, 1500))

  // Store mock result in sessionStorage
  const mockResult = {
    wsi_id,
    pred: ['HSIL', 'LSIL', 'Normal', 'ASC-US'][Math.floor(Math.random() * 4)],
    probs: {
      'HSIL': Math.random() * 0.5 + 0.3,
      'LSIL': Math.random() * 0.3,
      'Normal': Math.random() * 0.2,
      'ASC-US': Math.random() * 0.2
    },
    mode: 'placeholder'
  }

  // Normalize probabilities
  const total = Object.values(mockResult.probs).reduce((a: any, b: any) => a + b, 0)
  Object.keys(mockResult.probs).forEach(key => {
    mockResult.probs[key] = mockResult.probs[key] / total
  })

  sessionStorage.setItem(`result_${wsi_id}`, JSON.stringify(mockResult))

  return { task_id: `task_${Date.now()}`, status: 'completed' }
}

export async function fetchResults(wsi_id: string) {
  // Try to get from sessionStorage first (placeholder)
  const stored = sessionStorage.getItem(`result_${wsi_id}`)
  if (stored) {
    return JSON.parse(stored)
  }

  // Fallback to API
  try {
    const res = await fetch(`${API_BASE}/results/${encodeURIComponent(wsi_id)}`)
    if (!res.ok) throw new Error('Failed to get results')
    return res.json()
  } catch (err) {
    // Return null if no results available
    return null
  }
}

