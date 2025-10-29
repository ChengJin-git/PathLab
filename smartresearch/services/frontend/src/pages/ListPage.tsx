import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchWSIList } from '../api'

export default function ListPage() {
  const [items, setItems] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | undefined>()
  const [inferenceResults, setInferenceResults] = useState<Map<string, any>>(new Map())

  const taskDescription = sessionStorage.getItem('taskDescription') || ''
  const trainingCompleted = sessionStorage.getItem('trainingCompleted')
  const hasInferenceData = taskDescription && trainingCompleted

  useEffect(() => {
    fetchWSIList()
      .then((d) => {
        setItems(d.items || [])
        // Simulate inference results if training is completed
        if (hasInferenceData) {
          simulateInference(d.items || [])
        }
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false))
  }, [hasInferenceData])

  const simulateInference = (wsiList: any[]) => {
    const results = new Map()
    const labels = ['LUAD', 'LUSC', 'Normal']

    wsiList.forEach((wsi) => {
      // Simulate prediction
      const trueLabel = wsi.label || labels[Math.floor(Math.random() * labels.length)]
      const predLabel = Math.random() > 0.2 ? trueLabel : labels[Math.floor(Math.random() * labels.length)]

      // Generate probability distribution
      const probs: any = {}
      let remaining = 1.0
      labels.forEach((label, idx) => {
        if (idx === labels.length - 1) {
          probs[label] = remaining
        } else {
          const p = label === predLabel
            ? 0.5 + Math.random() * 0.4  // 50-90% for predicted class
            : Math.random() * remaining * 0.3
          probs[label] = p
          remaining -= p
        }
      })

      // Normalize probabilities
      const sum = Object.values(probs).reduce((a: any, b: any) => a + b, 0)
      Object.keys(probs).forEach(k => probs[k] /= sum)

      results.set(wsi.wsi_id, {
        pred: predLabel,
        confidence: probs[predLabel],
        probs: probs
      })
    })

    setInferenceResults(results)
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600"></div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">
        <p className="font-medium">Error loading WSI list</p>
        <p className="text-sm">{error}</p>
      </div>
    )
  }

  if (!items.length) {
    return (
      <div className="bg-yellow-50 border border-yellow-200 text-yellow-800 px-6 py-8 rounded-lg text-center">
        <p className="text-lg font-medium mb-2">No slides found</p>
        <p className="text-sm">Please upload slides first.</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Slide Browser</h1>
          <p className="text-gray-600 mt-1">
            Total {items.length} slides available
            {hasInferenceData && <span className="ml-2 text-primary-600">• Analysis results available</span>}
          </p>
        </div>
      </div>

      {/* Table */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Slide ID
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Known Diagnosis
                </th>
                {hasInferenceData && (
                  <>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      AI Suggestion
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Confidence
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Score Distribution
                    </th>
                  </>
                )}
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Action
                </th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {items.map((it) => {
                const result = inferenceResults.get(it.wsi_id)
                const isCorrect = result && it.label === result.pred

                return (
                  <tr key={it.wsi_id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                      {it.wsi_id}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600">
                      {it.label ? (
                        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800">
                          {it.label}
                        </span>
                      ) : (
                        <span className="text-gray-400">-</span>
                      )}
                    </td>
                    {hasInferenceData && result && (
                      <>
                        <td className="px-6 py-4 whitespace-nowrap text-sm">
                          <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                            isCorrect
                              ? 'bg-green-100 text-green-800'
                              : 'bg-red-100 text-red-800'
                          }`}>
                            {result.pred}
                          </span>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                          {(result.confidence * 100).toFixed(1)}%
                        </td>
                        <td className="px-6 py-4 text-sm">
                          <div className="space-y-1 min-w-[200px]">
                            {Object.entries(result.probs)
                              .sort((a: any, b: any) => b[1] - a[1])
                              .map(([cls, prob]: any) => (
                                <div key={cls} className="flex items-center space-x-2">
                                  <span className="text-xs text-gray-600 w-16">{cls}:</span>
                                  <div className="flex-1 bg-gray-200 rounded-full h-2">
                                    <div
                                      className="bg-primary-600 h-2 rounded-full transition-all"
                                      style={{ width: `${prob * 100}%` }}
                                    />
                                  </div>
                                  <span className="text-xs text-gray-900 w-12 text-right">
                                    {(prob * 100).toFixed(1)}%
                                  </span>
                                </div>
                              ))}
                          </div>
                        </td>
                      </>
                    )}
                    <td className="px-6 py-4 whitespace-nowrap text-sm">
                      <Link to={`/wsi/${encodeURIComponent(it.wsi_id)}`}>
                        <button className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-primary-600 hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500 transition-colors">
                          <span className="mr-2">🔬</span>
                          View
                        </button>
                      </Link>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

