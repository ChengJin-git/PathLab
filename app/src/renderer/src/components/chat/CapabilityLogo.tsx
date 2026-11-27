import { useEffect, useState } from 'react'
import { API_BASE } from '../../config'
import { apiFetchBlob } from '../../api/client'
import type { CapabilityEntry } from '../../api/capabilities'

function fallback(entry: CapabilityEntry) {
  const name = `${entry.id} ${entry.name}`.toLowerCase()
  if (/search|literature|检索|文献/.test(name)) return 'search'
  if (/statistic|analysis|统计|分析/.test(name)) return 'chart-no-axes-combined'
  if (/image|figure|图像|绘图/.test(name)) return 'image'
  if (/ppt|presentation|幻灯/.test(name)) return 'presentation'
  if (/data|数据/.test(name)) return 'database'
  if (/writing|polish|humanizer|写作|润色/.test(name)) return 'file-text'
  if (/pathlab|pathology|病理/.test(name)) return 'microscope'
  return entry.kind === 'connector' ? 'plug' : 'book-open'
}
export default function CapabilityLogo({ entry, className = '' }: { entry: CapabilityEntry; className?: string }) {
  const [url, setUrl] = useState('')
  const backup = `/images/capabilities/${fallback(entry)}.svg`
  useEffect(() => { setUrl(''); if (!entry.logo_revision) return; const controller = new AbortController(); let object = ''; apiFetchBlob(`${API_BASE}/capabilities/${encodeURIComponent(entry.id)}/logo?revision=${encodeURIComponent(entry.logo_revision)}`, { signal: controller.signal }).then(blob => { if (!controller.signal.aborted) { object = URL.createObjectURL(blob); setUrl(object) } }).catch(() => {}); return () => { controller.abort(); if (object) URL.revokeObjectURL(object) } }, [entry.id, entry.logo_revision])
  return <img src={url || backup} alt="" className={`h-10 w-10 shrink-0 rounded-xl bg-slate-50 object-contain p-2 ${className}`} onError={() => setUrl('')} />
}
