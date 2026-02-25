import { useState, useMemo, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { PackagePlus, Loader2, CheckCircle2, XCircle } from 'lucide-react'
import { AnnotationsMap, extractRegions, getExtractProgressSSEUrl } from '../../api/annotation'

interface CreateDatasetDialogProps {
  show: boolean
  onClose: () => void
  allAnnotations: AnnotationsMap
  labelColors: Record<string, string>
  sourceDatasetId?: string
  draftId?: string
}

type Phase = 'form' | 'extracting' | 'done' | 'error'

export function CreateDatasetDialog({
  show, onClose, allAnnotations, labelColors, sourceDatasetId, draftId,
}: CreateDatasetDialogProps) {
  const { t } = useTranslation()
  const [datasetName, setDatasetName] = useState('')
  const [taskType, setTaskType] = useState<'classification' | 'survival'>('classification')
  const [phase, setPhase] = useState<Phase>('form')
  const [progress, setProgress] = useState(0)
  const [errorMsg, setErrorMsg] = useState('')
  const eventSourceRef = useRef<EventSource | null>(null)

  // Compute summary
  const summary = useMemo(() => {
    const labelCounts: Record<string, number> = {}
    let totalRegions = 0
    const slideIds = new Set<string>()
    for (const [wsiId, regions] of Object.entries(allAnnotations)) {
      if (regions.length === 0) continue
      slideIds.add(wsiId)
      for (const r of regions) {
        totalRegions++
        labelCounts[r.label] = (labelCounts[r.label] || 0) + 1
      }
    }
    return { totalRegions, totalSlides: slideIds.size, labelCounts }
  }, [allAnnotations])

  // Cleanup EventSource on unmount
  useEffect(() => {
    return () => { eventSourceRef.current?.close() }
  }, [])

  // Reset state when dialog opens
  useEffect(() => {
    if (show) {
      setPhase('form')
      setDatasetName('')
      setTaskType('classification')
      setProgress(0)
      setErrorMsg('')
    }
  }, [show])

  const handleSubmit = async () => {
    if (!datasetName.trim() || summary.totalRegions === 0) return
    setPhase('extracting')
    setProgress(0)

    try {
      const resp = await extractRegions({
        draft_id: draftId,
        annotations: allAnnotations,
        dataset_name: datasetName.trim(),
        task_type: taskType,
      })

      // Start SSE progress streaming
      const sseUrl = getExtractProgressSSEUrl(resp.task_id)
      if (sseUrl) {
        const es = new EventSource(sseUrl)
        eventSourceRef.current = es

        es.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data)
            if (data.progress !== null && data.progress !== undefined) {
              setProgress(data.progress)
            }
            if (data.progress === 100 || data.done) {
              es.close()
              eventSourceRef.current = null
              setPhase('done')
            }
            if (data.progress === -1) {
              es.close()
              eventSourceRef.current = null
              setErrorMsg(t('annotation.extractFailed'))
              setPhase('error')
            }
          } catch { /* ignore parse errors */ }
        }

        es.onerror = () => {
          es.close()
          eventSourceRef.current = null
          // If we haven't gotten to done, treat as an error
          setPhase(prev => prev === 'extracting' ? 'error' : prev)
          setErrorMsg(t('annotation.extractFailed'))
        }
      }
    } catch (err: any) {
      setErrorMsg(err.message || t('annotation.extractFailed'))
      setPhase('error')
    }
  }

  if (!show) return null

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[200]">
      <div className="bg-white rounded-xl shadow-2xl max-w-md w-full mx-4 overflow-hidden">
        <div className="p-6">
          <div className="flex items-center gap-3 mb-4">
            <div className="p-2 bg-indigo-100 rounded-lg">
              <PackagePlus className="w-5 h-5 text-indigo-600" />
            </div>
            <h3 className="text-lg font-semibold text-gray-900">{t('annotation.createDatasetTitle')}</h3>
          </div>

          {phase === 'form' && (
            <>
              {/* Dataset name input */}
              <div className="mb-4">
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('annotation.datasetName')}</label>
                <input
                  type="text"
                  value={datasetName}
                  onChange={e => setDatasetName(e.target.value)}
                  placeholder={t('annotation.datasetNamePlaceholder')}
                  className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500 outline-none"
                  autoFocus
                />
              </div>

              {/* Task type selector */}
              <div className="mb-4">
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('annotation.taskType')}</label>
                <div className="flex gap-2">
                  {(['classification', 'survival'] as const).map(tt => (
                    <button
                      key={tt}
                      onClick={() => setTaskType(tt)}
                      className={`flex-1 px-3 py-2 text-xs font-medium rounded-lg border transition-all ${
                        taskType === tt
                          ? 'bg-indigo-50 border-indigo-300 text-indigo-700'
                          : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50'
                      }`}
                    >
                      {t(`annotation.${tt}`)}
                    </button>
                  ))}
                </div>
              </div>

              {/* Annotation summary */}
              <div className="bg-gray-50 rounded-lg p-3 mb-2">
                <h4 className="text-xs font-semibold text-gray-600 mb-2">{t('annotation.annotationSummary')}</h4>
                <div className="grid grid-cols-2 gap-2 text-xs mb-2">
                  <div className="flex justify-between"><span className="text-gray-500">{t('annotation.totalRegions')}</span><span className="font-medium text-gray-900">{summary.totalRegions}</span></div>
                  <div className="flex justify-between"><span className="text-gray-500">{t('annotation.totalSlides')}</span><span className="font-medium text-gray-900">{summary.totalSlides}</span></div>
                </div>
                <h4 className="text-xs font-semibold text-gray-600 mb-1">{t('annotation.labelDistribution')}</h4>
                <div className="space-y-1">
                  {Object.entries(summary.labelCounts).map(([label, count]) => (
                    <div key={label} className="flex items-center gap-2 text-xs">
                      <span className="w-2.5 h-2.5 rounded-full border border-gray-200 flex-shrink-0" style={{ backgroundColor: labelColors[label] || '#3b82f6' }} />
                      <span className="flex-1 text-gray-700 truncate">{label}</span>
                      <span className="text-gray-500">{count}</span>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}

          {phase === 'extracting' && (
            <div className="py-8 text-center">
              <Loader2 className="w-10 h-10 text-indigo-500 animate-spin mx-auto mb-4" />
              <p className="text-sm text-gray-600 mb-2">{t('annotation.extracting')}</p>
              <div className="w-full bg-gray-200 rounded-full h-2 mb-2">
                <div className="bg-indigo-600 h-2 rounded-full transition-all duration-300" style={{ width: `${progress}%` }} />
              </div>
              <p className="text-xs text-gray-500">{t('annotation.extractProgress', { progress })}</p>
            </div>
          )}

          {phase === 'done' && (
            <div className="py-8 text-center">
              <CheckCircle2 className="w-10 h-10 text-green-500 mx-auto mb-4" />
              <p className="text-sm font-medium text-gray-900">{t('annotation.extractComplete')}</p>
            </div>
          )}

          {phase === 'error' && (
            <div className="py-8 text-center">
              <XCircle className="w-10 h-10 text-red-500 mx-auto mb-4" />
              <p className="text-sm font-medium text-red-600">{errorMsg || t('annotation.extractFailed')}</p>
            </div>
          )}
        </div>

        <div className="flex gap-3 px-6 py-4 bg-gray-50 border-t">
          {phase === 'form' && (
            <>
              <button
                onClick={onClose}
                className="flex-1 px-4 py-2 text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
              >
                {t('common.cancel')}
              </button>
              <button
                onClick={handleSubmit}
                disabled={!datasetName.trim() || summary.totalRegions === 0}
                className="flex-1 px-4 py-2 text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
              >
                <PackagePlus className="w-4 h-4" />
                {t('annotation.createConfirm')}
              </button>
            </>
          )}
          {(phase === 'done' || phase === 'error') && (
            <button
              onClick={onClose}
              className="flex-1 px-4 py-2 text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
            >
              {t('common.close')}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

