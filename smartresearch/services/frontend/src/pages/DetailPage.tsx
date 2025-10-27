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
          <Link to="/wsi-list" style={styles.backLink}>← 返回列表</Link>
          <h3 style={styles.viewerTitle}>{wsi_id}</h3>
        </div>
        <div style={styles.viewerContainer}>
          {showViewer ? (
            <WSIViewer wsi_id={wsi_id} />
          ) : (
            <div style={styles.noViewer}>
              <div style={styles.placeholderViewer}>
                <p style={styles.placeholderText}>🔬 WSI Viewer</p>
                <p style={styles.placeholderSubtext}>加载中...</p>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Right: Analysis Panel */}
      <div style={styles.analysisPanel}>
        <div style={styles.section}>
          <h3>Metadata</h3>
          <table style={styles.infoTable}>
            <tbody>
              <tr><td style={styles.label}>Label:</td><td>{meta.label || '-'}</td></tr>
              <tr><td style={styles.label}>Case ID:</td><td>{meta.case_id || '-'}</td></tr>
              <tr><td style={styles.label}>Path:</td><td style={styles.path}>{meta.wsi_path || '-'}</td></tr>
            </tbody>
          </table>
        </div>

        <div style={styles.section}>
          <h3>AI Analysis</h3>
          <button onClick={onAnalyze} disabled={busy} style={styles.analyzeButton}>
            {busy ? 'Analyzing...' : '🔬 Run AI Analysis'}
          </button>

          {result && (
            <div style={styles.resultBox}>
              <div style={styles.predSection}>
                <strong>Prediction:</strong> <span style={styles.predValue}>{result.pred}</span>
                {(result.mode === 'stub' || result.mode === 'placeholder') && (
                  <span style={styles.badge}>{result.mode.toUpperCase()}</span>
                )}
              </div>

              {probEntries.length > 0 && (
                <div style={styles.probSection}>
                  <strong>Probabilities:</strong>
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
                <div style={styles.metaInfo}>Tiles: {result.num_tiles}</div>
              )}
            </div>
          )}
        </div>

        {/* Placeholder区域 */}
        <div style={styles.placeholderSection}>
          <h4 style={styles.placeholderTitle}>分析流程</h4>
          <div style={styles.placeholderGrid}>
            <div style={styles.placeholderBox}>
              <p style={styles.placeholderText}>📋 元数据</p>
            </div>
            <div style={styles.placeholderBox}>
              <p style={styles.placeholderText}>🔬 AI分析</p>
            </div>
            <div style={styles.placeholderBox}>
              <p style={styles.placeholderText}>📊 结果可视化</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

const styles = {
  layout: { display: 'flex', height: 'calc(100vh - 80px)', background: '#f6f8fa' },
  viewerPanel: { flex: 1, display: 'flex', flexDirection: 'column' as const, background: '#000' },
  viewerHeader: {
    display: 'flex',
    alignItems: 'center',
    padding: '12px 16px',
    background: '#1a1a1a',
    borderBottom: '1px solid #333'
  },
  backLink: { color: '#58a6ff', textDecoration: 'none', fontSize: 14, marginRight: 16 },
  viewerTitle: { color: 'white', margin: 0, fontSize: 16, fontWeight: 'normal' as const },
  viewerContainer: { flex: 1, position: 'relative' as const },
  noViewer: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    height: '100%',
    color: '#666',
    fontSize: 18
  },
  analysisPanel: {
    width: 400,
    background: 'white',
    borderLeft: '1px solid #d0d7de',
    overflowY: 'auto' as const,
    padding: 20
  },
  section: { marginBottom: 24 },
  infoTable: { width: '100%', marginTop: 12, fontSize: 14 },
  label: { fontWeight: 'bold' as const, paddingRight: 12, width: 80, paddingBottom: 8 },
  path: { fontSize: 12, color: '#666', wordBreak: 'break-all' as const },
  analyzeButton: {
    width: '100%',
    padding: '12px 20px',
    fontSize: 16,
    cursor: 'pointer',
    background: '#2da44e',
    color: 'white',
    border: 'none',
    borderRadius: 6,
    fontWeight: 'bold' as const,
    marginTop: 12
  },
  resultBox: { marginTop: 16, padding: 16, background: '#f6f8fa', borderRadius: 6 },
  predSection: { fontSize: 16, marginBottom: 16 },
  predValue: { color: '#2da44e', fontWeight: 'bold' as const, fontSize: 20, marginLeft: 8 },
  badge: {
    marginLeft: 8,
    padding: '2px 6px',
    background: '#ffc107',
    color: '#000',
    fontSize: 11,
    borderRadius: 3,
    fontWeight: 'bold' as const
  },
  probSection: { marginTop: 12 },
  probRow: { display: 'flex', alignItems: 'center', marginTop: 8 },
  className: { width: 80, fontSize: 13, fontWeight: 'bold' as const },
  barContainer: {
    flex: 1,
    height: 18,
    background: '#e1e4e8',
    borderRadius: 3,
    overflow: 'hidden' as const,
    marginRight: 8
  },
  bar: { height: '100%', background: '#0969da', transition: 'width 0.3s' },
  probValue: { width: 50, textAlign: 'right' as const, fontSize: 13, fontWeight: 'bold' as const },
  metaInfo: { marginTop: 12, fontSize: 12, color: '#666' },
  placeholderViewer: {
    padding: 40,
    background: '#2a2a2a',
    borderRadius: 8,
    border: '2px dashed #555'
  },
  placeholderSection: {
    marginTop: 24,
    paddingTop: 24,
    borderTop: '1px solid #e1e4e8'
  },
  placeholderTitle: {
    margin: '0 0 12px 0',
    fontSize: 14,
    fontWeight: 'bold' as const,
    color: '#333'
  },
  placeholderGrid: {
    display: 'grid',
    gridTemplateColumns: '1fr',
    gap: 8
  },
  placeholderBox: {
    padding: 12,
    background: '#f6f8fa',
    borderRadius: 6,
    border: '2px dashed #d0d7de',
    textAlign: 'center' as const
  },
  placeholderText: {
    margin: 0,
    fontSize: 12,
    color: '#666',
    fontWeight: 'bold' as const
  },
  placeholderSubtext: {
    margin: '4px 0 0 0',
    fontSize: 11,
    color: '#888'
  }
}

