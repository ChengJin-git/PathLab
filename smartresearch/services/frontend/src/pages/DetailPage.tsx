import React, { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { fetchWSIDetail, analyzeWSI, fetchResults } from '../api'
import WSIViewer from '../components/WSIViewer'

export default function DetailPage() {
  const { wsi_id = '' } = useParams()
  const [detail, setDetail] = useState<any>()
  const [result, setResult] = useState<any>()
  const [busy, setBusy] = useState(false)
  const [showViewer, setShowViewer] = useState(true)

  const load = () => fetchWSIDetail(wsi_id!).then(setDetail)

  useEffect(() => {
    load()
    fetchResults(wsi_id!).then(setResult).catch(() => {})
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

  if (!detail) return <div style={styles.analysisPanel}>Loading...</div>

  const meta = detail.meta || {}
  const probs = result?.probs || {}
  const probEntries = Object.entries(probs).sort((a: any, b: any) => b[1] - a[1])

  return (
    <div style={styles.layout}>
      {/* Left: WSI Viewer */}
      <div style={styles.viewerPanel}>
        <div style={styles.viewerHeader}>
          <Link to="/wsi-list" style={styles.backLink}>← Back to List</Link>
          <h3 style={styles.viewerTitle}>{wsi_id}</h3>
        </div>
        <div style={styles.viewerContainer}>
          {showViewer ? (
            <WSIViewer wsi_id={wsi_id} />
          ) : (
            <div style={styles.noViewer}>
              <div style={styles.placeholderViewer}>
                <p style={styles.placeholderText}>🔬 WSI Viewer</p>
                <p style={styles.placeholderSubtext}>Loading...</p>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Right: Analysis Panel */}
      <div style={styles.analysisPanel}>
        {/* Metadata Card */}
        <div style={styles.card}>
          <div style={styles.cardHeader}>
            <h3 style={styles.cardTitle}>Case Information</h3>
          </div>
          <div style={styles.cardBody}>
            <div style={styles.metaRow}>
              <span style={styles.metaLabel}>Diagnosis</span>
              <span style={styles.metaBadge}>{meta.label || '-'}</span>
            </div>
            <div style={styles.metaRow}>
              <span style={styles.metaLabel}>Case ID</span>
              <span style={styles.metaValue}>{meta.case_id || '-'}</span>
            </div>
            <div style={styles.metaRow}>
              <span style={styles.metaLabel}>File Path</span>
              <span style={styles.metaPath}>{meta.wsi_path || '-'}</span>
            </div>
          </div>
        </div>

        {/* AI Analysis Card */}
        <div style={styles.card}>
          <div style={styles.cardHeader}>
            <h3 style={styles.cardTitle}>AI-Assisted Diagnosis</h3>
          </div>
          <div style={styles.cardBody}>
            <button onClick={onAnalyze} disabled={busy} style={styles.analyzeButton}>
              {busy ? '⏳ Analyzing...' : '🔬 Run Analysis'}
            </button>

            {result && (
              <div style={styles.resultBox}>
                <div style={styles.predSection}>
                  <div style={styles.predLabel}>Suggested Diagnosis</div>
                  <div style={styles.predValueContainer}>
                    <span style={styles.predValue}>{result.pred}</span>
                    {(result.mode === 'stub' || result.mode === 'placeholder') && (
                      <span style={styles.badge}>DEMO</span>
                    )}
                  </div>
                </div>

                {probEntries.length > 0 && (
                  <div style={styles.probSection}>
                    <div style={styles.probLabel}>Confidence Scores</div>
                    {probEntries.map(([cls, prob]: any) => (
                      <div key={cls} style={styles.probRow}>
                        <span style={styles.className}>{cls}</span>
                        <div style={styles.barContainer}>
                          <div style={{...styles.bar, width: `${prob * 100}%`}} />
                        </div>
                        <span style={styles.probValue}>{(prob * 100).toFixed(1)}%</span>
                      </div>
                    ))}
                  </div>
                )}

                {result.num_tiles !== undefined && (
                  <div style={styles.tilesInfo}>
                    <span style={styles.tilesLabel}>Regions Analyzed</span>
                    <span style={styles.tilesValue}>{result.num_tiles}</span>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Workflow Card */}
        <div style={styles.card}>
          <div style={styles.cardHeader}>
            <h3 style={styles.cardTitle}>Analysis Steps</h3>
          </div>
          <div style={styles.cardBody}>
            <div style={styles.workflowStep}>
              <div style={styles.stepIcon}>✓</div>
              <div style={styles.stepContent}>
                <div style={styles.stepTitle}>Case Info</div>
                <div style={styles.stepDesc}>Case information loaded</div>
              </div>
            </div>
            <div style={styles.workflowStep}>
              <div style={result ? styles.stepIconActive : styles.stepIcon}>
                {result ? '✓' : '🔬'}
              </div>
              <div style={styles.stepContent}>
                <div style={styles.stepTitle}>AI Analysis</div>
                <div style={styles.stepDesc}>
                  {result ? 'Analysis complete' : 'Ready to analyze'}
                </div>
              </div>
            </div>
            <div style={styles.workflowStep}>
              <div style={styles.stepIcon}>📊</div>
              <div style={styles.stepContent}>
                <div style={styles.stepTitle}>Results</div>
                <div style={styles.stepDesc}>Interactive viewer</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

const styles = {
  layout: { display: 'flex', height: '100vh', background: '#f6f8fa' },
  viewerPanel: { flex: 1, display: 'flex', flexDirection: 'column' as const, background: '#000' },
  viewerHeader: {
    display: 'flex',
    alignItems: 'center',
    padding: '12px 20px',
    background: '#1a1a1a',
    borderBottom: '1px solid #333'
  },
  backLink: {
    color: '#58a6ff',
    textDecoration: 'none',
    fontSize: 14,
    marginRight: 16,
    fontWeight: 500 as const
  },
  viewerTitle: { color: 'white', margin: 0, fontSize: 16, fontWeight: 500 as const },
  viewerContainer: { flex: 1, position: 'relative' as const },
  noViewer: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    height: '100%',
    color: '#666',
    fontSize: 18
  },
  placeholderViewer: {
    padding: 40,
    background: '#2a2a2a',
    borderRadius: 8,
    border: '2px dashed #555'
  },
  placeholderText: {
    margin: 0,
    fontSize: 14,
    color: '#999',
    fontWeight: 500 as const
  },
  placeholderSubtext: {
    margin: '8px 0 0 0',
    fontSize: 12,
    color: '#666'
  },
  analysisPanel: {
    width: 380,
    background: '#f6f8fa',
    borderLeft: '1px solid #d0d7de',
    overflowY: 'auto' as const,
    padding: '20px 16px'
  },
  card: {
    background: 'white',
    borderRadius: 8,
    border: '1px solid #d0d7de',
    marginBottom: 16,
    overflow: 'hidden' as const
  },
  cardHeader: {
    padding: '12px 16px',
    borderBottom: '1px solid #d0d7de',
    background: '#f6f8fa'
  },
  cardTitle: {
    margin: 0,
    fontSize: 14,
    fontWeight: 600 as const,
    color: '#24292f'
  },
  cardBody: {
    padding: 16
  },
  metaRow: {
    display: 'flex',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    marginBottom: 12,
    fontSize: 13
  },
  metaLabel: {
    color: '#57606a',
    fontWeight: 500 as const,
    minWidth: 70
  },
  metaValue: {
    color: '#24292f',
    fontWeight: 500 as const,
    textAlign: 'right' as const,
    flex: 1
  },
  metaBadge: {
    background: '#ddf4ff',
    color: '#0969da',
    padding: '2px 8px',
    borderRadius: 12,
    fontSize: 12,
    fontWeight: 600 as const
  },
  metaPath: {
    fontSize: 11,
    color: '#57606a',
    wordBreak: 'break-all' as const,
    textAlign: 'right' as const,
    flex: 1,
    fontFamily: 'monospace'
  },
  analyzeButton: {
    width: '100%',
    padding: '10px 16px',
    fontSize: 14,
    cursor: 'pointer',
    background: '#2da44e',
    color: 'white',
    border: 'none',
    borderRadius: 6,
    fontWeight: 600 as const,
    transition: 'background 0.2s'
  },
  resultBox: {
    marginTop: 16,
    padding: 14,
    background: '#f6f8fa',
    borderRadius: 6,
    border: '1px solid #d0d7de'
  },
  predSection: {
    paddingBottom: 12,
    borderBottom: '1px solid #d0d7de',
    marginBottom: 12
  },
  predLabel: {
    fontSize: 12,
    color: '#57606a',
    fontWeight: 500 as const,
    marginBottom: 6
  },
  predValueContainer: {
    display: 'flex',
    alignItems: 'center',
    gap: 8
  },
  predValue: {
    color: '#2da44e',
    fontWeight: 600 as const,
    fontSize: 18
  },
  badge: {
    padding: '2px 8px',
    background: '#fff8c5',
    color: '#7d4e00',
    fontSize: 10,
    borderRadius: 12,
    fontWeight: 600 as const,
    textTransform: 'uppercase' as const
  },
  probSection: {
    marginTop: 0
  },
  probLabel: {
    fontSize: 12,
    color: '#57606a',
    fontWeight: 500 as const,
    marginBottom: 8
  },
  probRow: {
    display: 'flex',
    alignItems: 'center',
    marginBottom: 8
  },
  className: {
    width: 70,
    fontSize: 12,
    fontWeight: 500 as const,
    color: '#24292f'
  },
  barContainer: {
    flex: 1,
    height: 16,
    background: '#e1e4e8',
    borderRadius: 8,
    overflow: 'hidden' as const,
    marginRight: 8
  },
  bar: {
    height: '100%',
    background: 'linear-gradient(90deg, #0969da 0%, #54aeff 100%)',
    transition: 'width 0.3s ease'
  },
  probValue: {
    width: 45,
    textAlign: 'right' as const,
    fontSize: 12,
    fontWeight: 600 as const,
    color: '#24292f'
  },
  tilesInfo: {
    marginTop: 12,
    paddingTop: 12,
    borderTop: '1px solid #d0d7de',
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center'
  },
  tilesLabel: {
    fontSize: 12,
    color: '#57606a',
    fontWeight: 500 as const
  },
  tilesValue: {
    fontSize: 14,
    color: '#24292f',
    fontWeight: 600 as const
  },
  workflowStep: {
    display: 'flex',
    alignItems: 'flex-start',
    marginBottom: 16,
    gap: 12
  },
  stepIcon: {
    width: 32,
    height: 32,
    borderRadius: 16,
    background: '#f6f8fa',
    border: '2px solid #d0d7de',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: 14,
    flexShrink: 0
  },
  stepIconActive: {
    width: 32,
    height: 32,
    borderRadius: 16,
    background: '#ddf4ff',
    border: '2px solid #0969da',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: 14,
    flexShrink: 0,
    color: '#0969da'
  },
  stepContent: {
    flex: 1
  },
  stepTitle: {
    fontSize: 13,
    fontWeight: 600 as const,
    color: '#24292f',
    marginBottom: 2
  },
  stepDesc: {
    fontSize: 12,
    color: '#57606a'
  }
}

