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

  if (!detail) {
    return (
      <div style={styles.loadingContainer}>
        <div style={styles.loadingSpinner}>
          <div style={styles.spinner}></div>
          <p style={styles.loadingText}>Loading slide information...</p>
        </div>
      </div>
    )
  }

  const meta = detail.meta || {}
  const probs = result?.probs || {}
  const probEntries = Object.entries(probs).sort((a: any, b: any) => b[1] - a[1])

  return (
    <div style={styles.layout}>
      {/* Left: WSI Viewer */}
      <div style={styles.viewerPanel}>
        <div style={styles.viewerHeader}>
          <Link to="/wsi-list" style={styles.backLink}>
            <span style={styles.backIcon}>←</span> Back to List
          </Link>
          <div style={styles.headerDivider}></div>
          <h3 style={styles.viewerTitle}>
            <span style={styles.slideIcon}>🔬</span>
            {wsi_id}
          </h3>
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
            <div style={styles.cardHeaderIcon}>📋</div>
            <h3 style={styles.cardTitle}>Case Information</h3>
          </div>
          <div style={styles.cardBody}>
            {/* Primary Info */}
            <div style={styles.primaryInfo}>
              <div style={styles.diagnosisSection}>
                <span style={styles.diagnosisLabel}>Diagnosis</span>
                <span style={styles.diagnosisBadge}>{meta.label || 'Unknown'}</span>
              </div>
            </div>

            {/* Patient Info Grid */}
            <div style={styles.infoGrid}>
              <div style={styles.infoItem}>
                <span style={styles.infoLabel}>Case ID</span>
                <span style={styles.infoValue}>{meta.case_id || '-'}</span>
              </div>
              {meta.age && (
                <div style={styles.infoItem}>
                  <span style={styles.infoLabel}>Age</span>
                  <span style={styles.infoValue}>{meta.age} years</span>
                </div>
              )}
              {meta.gender && (
                <div style={styles.infoItem}>
                  <span style={styles.infoLabel}>Gender</span>
                  <span style={styles.infoValue}>{meta.gender}</span>
                </div>
              )}
              {meta.source && (
                <div style={styles.infoItem}>
                  <span style={styles.infoLabel}>Source</span>
                  <span style={styles.infoValue}>{meta.source}</span>
                </div>
              )}
            </div>

            {/* File Path */}
            <div style={styles.filePathSection}>
              <span style={styles.filePathHubel}>File Path</span>
              <span style={styles.filePathValue}>{meta.wsi_path || '-'}</span>
            </div>
          </div>
        </div>

        {/* AI Analysis Card */}
        <div style={styles.card}>
          <div style={styles.cardHeader}>
            <div style={styles.cardHeaderIcon}>🤖</div>
            <h3 style={styles.cardTitle}>AI-Assisted Diagnosis</h3>
          </div>
          <div style={styles.cardBody}>
            <button
              onClick={onAnalyze}
              disabled={busy}
              style={busy ? styles.analyzeButtonDisabled : styles.analyzeButton}
            >
              {busy ? (
                <>
                  <span style={styles.buttonSpinner}></span>
                  <span>Analyzing...</span>
                </>
              ) : (
                <>
                  <span style={styles.buttonIcon}>▶</span>
                  <span>Run Analysis</span>
                </>
              )}
            </button>

            {result && (
              <div style={styles.resultBox}>
                <div style={styles.predSection}>
                  <div style={styles.predHeader}>
                    <span style={styles.predLabel}>AI Prediction</span>
                    {(result.mode === 'stub' || result.mode === 'placeholder') && (
                      <span style={styles.demoBadge}>DEMO MODE</span>
                    )}
                  </div>
                  <div style={styles.predValueBox}>
                    <span style={styles.predValue}>{result.pred}</span>
                  </div>
                </div>

                {probEntries.length > 0 && (
                  <div style={styles.probSection}>
                    <div style={styles.probHeader}>
                      <span style={styles.probLabel}>Confidence Distribution</span>
                      <span style={styles.probCount}>{probEntries.length} classes</span>
                    </div>
                    <div style={styles.probList}>
                      {probEntries.map(([cls, prob]: any, index: number) => (
                        <div key={cls} style={styles.probRow}>
                          <div style={styles.probRank}>{index + 1}</div>
                          <div style={styles.probContent}>
                            <div style={styles.probTop}>
                              <span style={styles.className}>{cls}</span>
                              <span style={styles.probValue}>{(prob * 100).toFixed(1)}%</span>
                            </div>
                            <div style={styles.barContainer}>
                              <div
                                style={{
                                  ...styles.bar,
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
                  <div style={styles.statsSection}>
                    <div style={styles.statItem}>
                      <span style={styles.statIcon}>🔍</span>
                      <div style={styles.statContent}>
                        <span style={styles.statLabel}>Regions Analyzed</span>
                        <span style={styles.statValue}>{result.num_tiles.toLocaleString()}</span>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Workflow Card */}
        <div style={styles.card}>
          <div style={styles.cardHeader}>
            <div style={styles.cardHeaderIcon}>📊</div>
            <h3 style={styles.cardTitle}>Analysis Steps</h3>
          </div>
          <div style={styles.cardBody}>
            <div style={styles.timeline}>
              <div style={styles.workflowStep}>
                <div style={styles.stepIconCompleted}>
                  <span style={styles.checkmark}>✓</span>
                </div>
                <div style={styles.stepLine}></div>
                <div style={styles.stepContent}>
                  <div style={styles.stepTitle}>Case Info</div>
                  <div style={styles.stepDesc}>Case information loaded</div>
                </div>
              </div>
              <div style={styles.workflowStep}>
                <div style={result ? styles.stepIconCompleted : busy ? styles.stepIconActive : styles.stepIconPending}>
                  {result ? (
                    <span style={styles.checkmark}>✓</span>
                  ) : busy ? (
                    <span style={styles.stepSpinner}></span>
                  ) : (
                    <span style={styles.stepNumber}>2</span>
                  )}
                </div>
                <div style={styles.stepLine}></div>
                <div style={styles.stepContent}>
                  <div style={styles.stepTitle}>AI Analysis</div>
                  <div style={styles.stepDesc}>
                    {result ? 'Analysis complete' : busy ? 'Analyzing...' : 'Ready to analyze'}
                  </div>
                </div>
              </div>
              <div style={styles.workflowStep}>
                <div style={result ? styles.stepIconCompleted : styles.stepIconPending}>
                  {result ? (
                    <span style={styles.checkmark}>✓</span>
                  ) : (
                    <span style={styles.stepNumber}>3</span>
                  )}
                </div>
                <div style={styles.stepContent}>
                  <div style={styles.stepTitle}>Results</div>
                  <div style={styles.stepDesc}>
                    {result ? 'Interactive viewer available' : 'Pending analysis'}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

const styles = {
  // Loading state
  loadingContainer: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    height: '100vh',
    background: '#f6f8fa'
  },
  loadingSpinner: {
    textAlign: 'center' as const
  },
  spinner: {
    width: 48,
    height: 48,
    border: '4px solid #e1e4e8',
    borderTop: '4px solid #0969da',
    borderRadius: '50%',
    animation: 'spin 1s linear infinite',
    margin: '0 auto 16px'
  },
  loadingText: {
    color: '#57606a',
    fontSize: 14,
    margin: 0
  },

  // Layout
  layout: {
    display: 'flex',
    height: '100vh',
    background: '#f6f8fa'
  },
  viewerPanel: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column' as const,
    background: '#000'
  },
  viewerHeader: {
    display: 'flex',
    alignItems: 'center',
    padding: '14px 24px',
    background: 'linear-gradient(135deg, #1a1a1a 0%, #2a2a2a 100%)',
    borderBottom: '1px solid #404040',
    gap: 16
  },
  backLink: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    color: '#58a6ff',
    textDecoration: 'none',
    fontSize: 14,
    fontWeight: 500 as const,
    padding: '6px 12px',
    borderRadius: 6,
    transition: 'all 0.2s',
    background: 'rgba(88, 166, 255, 0.1)',
    border: '1px solid rgba(88, 166, 255, 0.2)'
  },
  backIcon: {
    fontSize: 16
  },
  headerDivider: {
    width: 1,
    height: 20,
    background: '#404040'
  },
  viewerTitle: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    color: 'white',
    margin: 0,
    fontSize: 16,
    fontWeight: 600 as const,
    flex: 1
  },
  slideIcon: {
    fontSize: 18
  },
  viewerContainer: {
    flex: 1,
    position: 'relative' as const
  },
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
    width: 420,
    background: '#f6f8fa',
    borderLeft: '1px solid #d0d7de',
    overflowY: 'auto' as const,
    padding: '24px 20px'
  },
  // Card styles
  card: {
    background: 'white',
    borderRadius: 12,
    border: '1px solid #d0d7de',
    marginBottom: 20,
    overflow: 'hidden' as const,
    boxShadow: '0 1px 3px rgba(0, 0, 0, 0.05)'
  },
  cardHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    padding: '14px 18px',
    borderBottom: '1px solid #e1e4e8',
    background: 'linear-gradient(135deg, #f6f8fa 0%, #ffffff 100%)'
  },
  cardHeaderIcon: {
    fontSize: 18,
    lineHeight: 1
  },
  cardTitle: {
    margin: 0,
    fontSize: 15,
    fontWeight: 600 as const,
    color: '#24292f'
  },
  cardBody: {
    padding: 18
  },
  // Case Information styles
  primaryInfo: {
    marginBottom: 20,
    paddingBottom: 18,
    borderBottom: '2px solid #e1e4e8'
  },
  diagnosisSection: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 8
  },
  diagnosisLabel: {
    fontSize: 12,
    color: '#57606a',
    fontWeight: 600 as const,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.5px'
  },
  diagnosisBadge: {
    display: 'inline-block',
    background: 'linear-gradient(135deg, #ddf4ff 0%, #b6e3ff 100%)',
    color: '#0969da',
    padding: '8px 16px',
    borderRadius: 8,
    fontSize: 16,
    fontWeight: 700 as const,
    border: '2px solid #0969da',
    textAlign: 'center' as const
  },
  infoGrid: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: 14,
    marginBottom: 16
  },
  infoItem: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 4,
    padding: 12,
    background: '#f6f8fa',
    borderRadius: 8,
    border: '1px solid #e1e4e8'
  },
  infoLabel: {
    fontSize: 11,
    color: '#57606a',
    fontWeight: 600 as const,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.3px'
  },
  infoValue: {
    fontSize: 14,
    color: '#24292f',
    fontWeight: 600 as const
  },
  filePathSection: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 6,
    padding: 12,
    background: '#f6f8fa',
    borderRadius: 8,
    border: '1px solid #e1e4e8'
  },
  filePathHubel: {
    fontSize: 11,
    color: '#57606a',
    fontWeight: 600 as const,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.3px'
  },
  filePathValue: {
    fontSize: 11,
    color: '#24292f',
    fontFamily: 'monospace',
    wordBreak: 'break-all' as const,
    lineHeight: 1.5
  },
  // Analysis button styles
  analyzeButton: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    width: '100%',
    padding: '12px 20px',
    fontSize: 14,
    cursor: 'pointer',
    background: 'linear-gradient(135deg, #2da44e 0%, #26a641 100%)',
    color: 'white',
    border: 'none',
    borderRadius: 8,
    fontWeight: 600 as const,
    transition: 'all 0.2s',
    boxShadow: '0 2px 4px rgba(45, 164, 78, 0.2)'
  },
  analyzeButtonDisabled: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    width: '100%',
    padding: '12px 20px',
    fontSize: 14,
    cursor: 'not-allowed',
    background: '#94d3a2',
    color: 'white',
    border: 'none',
    borderRadius: 8,
    fontWeight: 600 as const,
    opacity: 0.7
  },
  buttonIcon: {
    fontSize: 12
  },
  buttonSpinner: {
    width: 14,
    height: 14,
    border: '2px solid rgba(255, 255, 255, 0.3)',
    borderTop: '2px solid white',
    borderRadius: '50%',
    animation: 'spin 0.8s linear infinite'
  },
  // Result box styles
  resultBox: {
    marginTop: 18,
    padding: 0,
    background: 'transparent'
  },
  predSection: {
    padding: 16,
    background: 'linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%)',
    borderRadius: 10,
    border: '2px solid #10b981',
    marginBottom: 16
  },
  predHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 10
  },
  predLabel: {
    fontSize: 12,
    color: '#065f46',
    fontWeight: 600 as const,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.5px'
  },
  demoBadge: {
    padding: '3px 8px',
    background: '#fef3c7',
    color: '#92400e',
    fontSize: 10,
    borderRadius: 6,
    fontWeight: 700 as const,
    border: '1px solid #fbbf24'
  },
  predValueBox: {
    padding: 12,
    background: 'white',
    borderRadius: 8,
    border: '1px solid #10b981'
  },
  predValue: {
    color: '#059669',
    fontWeight: 700 as const,
    fontSize: 20,
    display: 'block',
    textAlign: 'center' as const
  },
  // Probability section styles
  probSection: {
    padding: 16,
    background: '#f6f8fa',
    borderRadius: 10,
    border: '1px solid #d0d7de',
    marginBottom: 16
  },
  probHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 14
  },
  probLabel: {
    fontSize: 12,
    color: '#24292f',
    fontWeight: 600 as const,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.5px'
  },
  probCount: {
    fontSize: 11,
    color: '#57606a',
    fontWeight: 500 as const,
    padding: '2px 8px',
    background: '#e1e4e8',
    borderRadius: 6
  },
  probList: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 12
  },
  probRow: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: 10
  },
  probRank: {
    width: 24,
    height: 24,
    borderRadius: 12,
    background: '#e1e4e8',
    color: '#57606a',
    fontSize: 11,
    fontWeight: 700 as const,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
    marginTop: 2
  },
  probContent: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 6
  },
  probTop: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between'
  },
  className: {
    fontSize: 13,
    fontWeight: 600 as const,
    color: '#24292f'
  },
  probValue: {
    fontSize: 13,
    fontWeight: 700 as const,
    color: '#0969da'
  },
  barContainer: {
    height: 8,
    background: '#e1e4e8',
    borderRadius: 4,
    overflow: 'hidden' as const
  },
  bar: {
    height: '100%',
    borderRadius: 4,
    transition: 'width 0.5s ease'
  },
  // Stats section styles
  statsSection: {
    padding: 14,
    background: '#f6f8fa',
    borderRadius: 10,
    border: '1px solid #d0d7de'
  },
  statItem: {
    display: 'flex',
    alignItems: 'center',
    gap: 12
  },
  statIcon: {
    fontSize: 24,
    lineHeight: 1
  },
  statContent: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 4
  },
  statLabel: {
    fontSize: 11,
    color: '#57606a',
    fontWeight: 600 as const,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.3px'
  },
  statValue: {
    fontSize: 18,
    color: '#24292f',
    fontWeight: 700 as const
  },
  // Workflow/Timeline styles
  timeline: {
    position: 'relative' as const
  },
  workflowStep: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: 14,
    position: 'relative' as const,
    paddingBottom: 20
  },
  stepIconCompleted: {
    width: 36,
    height: 36,
    borderRadius: 18,
    background: 'linear-gradient(135deg, #10b981 0%, #059669 100%)',
    border: '2px solid #059669',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: 16,
    flexShrink: 0,
    color: 'white',
    fontWeight: 700 as const,
    boxShadow: '0 2px 4px rgba(16, 185, 129, 0.3)',
    zIndex: 1
  },
  stepIconActive: {
    width: 36,
    height: 36,
    borderRadius: 18,
    background: 'linear-gradient(135deg, #3b82f6 0%, #2563eb 100%)',
    border: '2px solid #2563eb',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: 16,
    flexShrink: 0,
    color: 'white',
    fontWeight: 700 as const,
    boxShadow: '0 2px 4px rgba(59, 130, 246, 0.3)',
    zIndex: 1
  },
  stepIconPending: {
    width: 36,
    height: 36,
    borderRadius: 18,
    background: '#f6f8fa',
    border: '2px solid #d0d7de',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: 14,
    flexShrink: 0,
    color: '#57606a',
    fontWeight: 700 as const,
    zIndex: 1
  },
  stepLine: {
    position: 'absolute' as const,
    left: 17,
    top: 36,
    width: 2,
    height: 20,
    background: '#e1e4e8'
  },
  checkmark: {
    fontSize: 18
  },
  stepNumber: {
    fontSize: 14
  },
  stepSpinner: {
    width: 18,
    height: 18,
    border: '2px solid rgba(255, 255, 255, 0.3)',
    borderTop: '2px solid white',
    borderRadius: '50%',
    animation: 'spin 0.8s linear infinite'
  },
  stepContent: {
    flex: 1,
    paddingTop: 4
  },
  stepTitle: {
    fontSize: 14,
    fontWeight: 600 as const,
    color: '#24292f',
    marginBottom: 4
  },
  stepDesc: {
    fontSize: 12,
    color: '#57606a',
    lineHeight: 1.5
  }
}

// Add CSS animation for spinners
const styleSheet = document.createElement('style')
styleSheet.textContent = `
  @keyframes spin {
    0% { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
  }
`
document.head.appendChild(styleSheet)

