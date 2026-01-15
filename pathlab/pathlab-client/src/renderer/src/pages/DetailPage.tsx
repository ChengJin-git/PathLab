import React, { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { fetchWSIDetail, analyzeWSI, fetchResults } from '../api'
import WSIViewer from '../components/WSIViewer'
import { Card, Button } from '../components/common'
import { ArrowLeft, Microscope, ClipboardList, Activity, Check, Loader2 } from 'lucide-react'

export default function DetailPage() {
  const { wsi_id = '' } = useParams()
  const [detail, setDetail] = useState<any>()
  const [result, setResult] = useState<any>()
  const [busy, setBusy] = useState(false)
  const [showViewer, setShowViewer] = useState(true)

  const load = () => fetchWSIDetail(wsi_id!).then(setDetail)

  useEffect(() => {
    load()
    fetchResults(wsi_id!).then(setResult).catch(() => { })
  }, [wsi_id])

  const onAnalyze = async () => {
    setBusy(true)
    try {
      await analyzeWSI(wsi_id!, {})
      const r = await fetchResults(wsi_id!)
      setResult(r)
    } finally {
      setBusy(false)
    }
  }

  if (!detail) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-gray-50">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="w-8 h-8 animate-spin text-blue-500" />
          <p className="text-gray-500 font-medium">Loading slide information...</p>
        </div>
      </div>
    )
  }

  const meta = detail.meta || {}
  const probs = result?.probs || {}
  const probEntries = Object.entries(probs).sort((a: any, b: any) => b[1] - a[1])

  return (
    <div className="flex h-screen bg-gray-50 overflow-hidden">
      {/* Left: WSI Viewer */}
      <div className="flex-1 flex flex-col bg-gray-50 relative">
        <div className="flex items-center px-6 py-3 bg-white border-b border-gray-200 gap-4 shadow-sm z-10">
          <Link
            to="/wsi-list"
            className="flex items-center gap-2 text-gray-600 hover:text-gray-900 hover:bg-gray-100 text-sm font-medium px-3 py-1.5 rounded-md transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to List
          </Link>
          <div className="w-px h-5 bg-gray-200"></div>
          <h3 className="flex items-center gap-2 text-gray-900 text-base font-semibold flex-1">
            <Microscope className="w-4 h-4 text-blue-600" />
            {wsi_id}
          </h3>
        </div>
        <div className="flex-1 relative bg-gray-100">
          {showViewer ? (
            <WSIViewer wsi_id={wsi_id} />
          ) : (
            <div className="flex items-center justify-center h-full text-gray-500 text-lg">
              <div className="p-10 bg-white rounded-lg border-2 border-dashed border-gray-200 text-center shadow-sm">
                <p className="m-0 text-sm text-gray-900 font-medium">🔬 WSI Viewer</p>
                <p className="mt-2 text-xs text-gray-500">Loading...</p>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Right: Analysis Panel */}
      <div className="w-[420px] bg-gray-50 border-l border-gray-200 overflow-y-auto p-6">
        {/* Metadata Card */}
        <Card className="mb-5 overflow-hidden">
          <div className="flex items-center gap-2.5 px-4 py-3.5 border-b border-gray-200 bg-gradient-to-br from-gray-50 to-white">
            <ClipboardList className="w-4 h-4 text-gray-500" />
            <h3 className="m-0 text-[15px] font-semibold text-gray-900">Case Information</h3>
          </div>
          <div className="p-4">
            {/* Primary Info */}
            <div className="mb-5 pb-4 border-b-2 border-gray-100">
              <div className="flex flex-col gap-2">
                <span className="text-xs text-gray-500 font-semibold uppercase tracking-wider">Diagnosis</span>
                <span className="inline-block bg-gradient-to-br from-blue-50 to-blue-100 text-blue-700 px-4 py-2 rounded-lg text-base font-bold border-2 border-blue-600 text-center">
                  {meta.label || 'Unknown'}
                </span>
              </div>
            </div>

            {/* Patient Info Grid */}
            <div className="grid grid-cols-2 gap-3.5 mb-4">
              <div className="flex flex-col gap-1 p-3 bg-gray-50 rounded-lg border border-gray-200">
                <span className="text-[11px] text-gray-500 font-semibold uppercase tracking-wider">Case ID</span>
                <span className="text-sm text-gray-900 font-semibold">{meta.case_id || '-'}</span>
              </div>
              {meta.age && (
                <div className="flex flex-col gap-1 p-3 bg-gray-50 rounded-lg border border-gray-200">
                  <span className="text-[11px] text-gray-500 font-semibold uppercase tracking-wider">Age</span>
                  <span className="text-sm text-gray-900 font-semibold">{meta.age} years</span>
                </div>
              )}
              {meta.gender && (
                <div className="flex flex-col gap-1 p-3 bg-gray-50 rounded-lg border border-gray-200">
                  <span className="text-[11px] text-gray-500 font-semibold uppercase tracking-wider">Gender</span>
                  <span className="text-sm text-gray-900 font-semibold">{meta.gender}</span>
                </div>
              )}
              {meta.source && (
                <div className="flex flex-col gap-1 p-3 bg-gray-50 rounded-lg border border-gray-200">
                  <span className="text-[11px] text-gray-500 font-semibold uppercase tracking-wider">Source</span>
                  <span className="text-sm text-gray-900 font-semibold">{meta.source}</span>
                </div>
              )}
            </div>

            {/* File Path */}
            <div className="flex flex-col gap-1.5 p-3 bg-gray-50 rounded-lg border border-gray-200">
              <span className="text-[11px] text-gray-500 font-semibold uppercase tracking-wider">File Path</span>
              <span className="text-[11px] text-gray-900 font-mono break-all leading-relaxed">{meta.wsi_path || '-'}</span>
            </div>
          </div>
        </Card>

        {/* AI Analysis Card */}
        <Card className="mb-5 overflow-hidden">
          <div className="flex items-center gap-2.5 px-4 py-3.5 border-b border-gray-200 bg-gradient-to-br from-gray-50 to-white">
            <Activity className="w-4 h-4 text-gray-500" />
            <h3 className="m-0 text-[15px] font-semibold text-gray-900">AI-Assisted Diagnosis</h3>
          </div>
          <div className="p-4">
            <Button
              onClick={onAnalyze}
              disabled={busy}
              className={`w-full gap-2 ${busy ? 'bg-green-300' : 'bg-gradient-to-br from-green-600 to-green-700 hover:from-green-700 hover:to-green-800'}`}
            >
              {busy ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  <span>Analyzing...</span>
                </>
              ) : (
                <>
                  <Activity className="w-3.5 h-3.5" />
                  <span>Run Analysis</span>
                </>
              )}
            </Button>

            {result && (
              <div className="mt-4.5 p-0 bg-transparent">
                <div className="p-4 bg-gradient-to-br from-green-50 to-green-100 rounded-lg border-2 border-green-500 mb-4">
                  <div className="flex items-center justify-between mb-2.5">
                    <span className="text-xs text-green-800 font-semibold uppercase tracking-wider">AI Prediction</span>
                    {(result.mode === 'stub' || result.mode === 'placeholder') && (
                      <span className="px-2 py-0.5 bg-amber-100 text-amber-800 text-[10px] rounded-md font-bold border border-amber-300">DEMO MODE</span>
                    )}
                  </div>
                  <div className="p-3 bg-white rounded-lg border border-green-500">
                    <span className="text-green-600 font-bold text-xl block text-center">{result.pred}</span>
                  </div>
                </div>

                {probEntries.length > 0 && (
                  <div className="p-4 bg-gray-50 rounded-lg border border-gray-200 mb-4">
                    <div className="flex items-center justify-between mb-3.5">
                      <span className="text-xs text-gray-900 font-semibold uppercase tracking-wider">Confidence Distribution</span>
                      <span className="text-[11px] text-gray-600 font-medium px-2 py-0.5 bg-gray-200 rounded-md">{probEntries.length} classes</span>
                    </div>
                    <div className="flex flex-col gap-3">
                      {probEntries.map(([cls, prob]: any, index: number) => (
                        <div key={cls} className="flex items-start gap-2.5">
                          <div className="w-6 h-6 rounded-full bg-gray-200 text-gray-600 text-[11px] font-bold flex items-center justify-center flex-shrink-0 mt-0.5">{index + 1}</div>
                          <div className="flex-1 flex flex-col gap-1.5">
                            <div className="flex items-center justify-between">
                              <span className="text-[13px] font-semibold text-gray-900">{cls}</span>
                              <span className="text-[13px] font-bold text-blue-600">{(prob * 100).toFixed(1)}%</span>
                            </div>
                            <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
                              <div
                                className="h-full rounded-full transition-all duration-500"
                                style={{
                                  width: `${prob * 100}%`,
                                  background: index === 0
                                    ? 'linear-gradient(90deg, #10b981 0%, #34d399 100%)'
                                    : 'linear-gradient(90deg, #3b82f6 0%, #60a5fa 100%)'
                                }}
                              />
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {result.num_tiles !== undefined && (
                  <div className="p-3.5 bg-gray-50 rounded-lg border border-gray-200">
                    <div className="flex items-center gap-3">
                      <span className="text-2xl leading-none">🔍</span>
                      <div className="flex flex-col gap-1">
                        <span className="text-[11px] text-gray-600 font-semibold uppercase tracking-wider">Regions Analyzed</span>
                        <span className="text-lg text-gray-900 font-bold">{result.num_tiles.toLocaleString()}</span>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </Card>

        {/* Workflow Card */}
        <Card className="mb-5 overflow-hidden">
          <div className="flex items-center gap-2.5 px-4 py-3.5 border-b border-gray-200 bg-gradient-to-br from-gray-50 to-white">
            <Activity className="w-4 h-4 text-gray-500" />
            <h3 className="m-0 text-[15px] font-semibold text-gray-900">Analysis Steps</h3>
          </div>
          <div className="p-4">
            <div className="relative">
              <div className="flex items-start gap-3.5 relative pb-5">
                <div className="w-9 h-9 rounded-full bg-gradient-to-br from-green-500 to-green-600 border-2 border-green-600 flex items-center justify-center text-base flex-shrink-0 text-white font-bold shadow-sm z-10">
                  <Check className="w-4 h-4" />
                </div>
                <div className="absolute left-[17px] top-9 w-0.5 h-5 bg-gray-200"></div>
                <div className="flex-1 pt-1">
                  <div className="text-sm font-semibold text-gray-900 mb-1">Case Info</div>
                  <div className="text-xs text-gray-600 leading-relaxed">Case information loaded</div>
                </div>
              </div>
              <div className="flex items-start gap-3.5 relative pb-5">
                <div className={`w-9 h-9 rounded-full border-2 flex items-center justify-center text-base flex-shrink-0 font-bold shadow-sm z-10 ${result
                    ? 'bg-gradient-to-br from-green-500 to-green-600 border-green-600 text-white'
                    : busy
                      ? 'bg-gradient-to-br from-blue-500 to-blue-600 border-blue-600 text-white'
                      : 'bg-gray-50 border-gray-300 text-gray-600'
                  }`}>
                  {result ? (
                    <Check className="w-4 h-4" />
                  ) : busy ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <span className="text-sm">2</span>
                  )}
                </div>
                <div className="absolute left-[17px] top-9 w-0.5 h-5 bg-gray-200"></div>
                <div className="flex-1 pt-1">
                  <div className="text-sm font-semibold text-gray-900 mb-1">AI Analysis</div>
                  <div className="text-xs text-gray-600 leading-relaxed">
                    {result ? 'Analysis complete' : busy ? 'Analyzing...' : 'Ready to analyze'}
                  </div>
                </div>
              </div>
              <div className="flex items-start gap-3.5 relative">
                <div className={`w-9 h-9 rounded-full border-2 flex items-center justify-center text-base flex-shrink-0 font-bold shadow-sm z-10 ${result
                    ? 'bg-gradient-to-br from-green-500 to-green-600 border-green-600 text-white'
                    : 'bg-gray-50 border-gray-300 text-gray-600'
                  }`}>
                  {result ? (
                    <Check className="w-4 h-4" />
                  ) : (
                    <span className="text-sm">3</span>
                  )}
                </div>
                <div className="flex-1 pt-1">
                  <div className="text-sm font-semibold text-gray-900 mb-1">Results</div>
                  <div className="text-xs text-gray-600 leading-relaxed">
                    {result ? 'Interactive viewer available' : 'Pending analysis'}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </Card>
      </div>
    </div>
  )
}
