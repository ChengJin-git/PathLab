import React, { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchStats } from '../api'

interface Stats {
  wsi_count: number
  task_count: number
  completed_count: number
  results_count: number
  labels: Record<string, number>
}

export default function DashboardPage() {
  const navigate = useNavigate()
  const [stats, setStats] = useState<Stats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    loadStats()
    // Refresh stats every 5 seconds
    const interval = setInterval(loadStats, 5000)
    return () => clearInterval(interval)
  }, [])

  const loadStats = async () => {
    try {
      const data = await fetchStats()
      setStats(data)
      setError(null)
    } catch (err) {
      setError(String(err))
    } finally {
      setLoading(false)
    }
  }

  const runningCount = stats ? stats.task_count - stats.completed_count : 0

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <h1 style={styles.title}>SmartResearch Dashboard</h1>
        <p style={styles.subtitle}>System Overview and Statistics</p>
      </div>

      {loading && (
        <div style={styles.loading}>Loading statistics...</div>
      )}

      {error && (
        <div style={styles.error}>Error loading stats: {error}</div>
      )}

      {!loading && stats && (
        <>
          {/* Main Statistics Cards */}
          <div style={styles.statsGrid}>
            <div style={{...styles.statCard, ...styles.statCardPrimary}}>
              <div style={styles.statIcon}>🔬</div>
              <div style={styles.statContent}>
                <div style={styles.statValue}>{stats.wsi_count}</div>
                <div style={styles.statLabel}>Total WSI Files</div>
              </div>
            </div>

            <div style={{...styles.statCard, ...styles.statCardSuccess}}>
              <div style={styles.statIcon}>✅</div>
              <div style={styles.statContent}>
                <div style={styles.statValue}>{stats.completed_count}</div>
                <div style={styles.statLabel}>Completed Tasks</div>
              </div>
            </div>

            <div style={{...styles.statCard, ...styles.statCardWarning}}>
              <div style={styles.statIcon}>⚙️</div>
              <div style={styles.statContent}>
                <div style={styles.statValue}>{runningCount}</div>
                <div style={styles.statLabel}>Running Tasks</div>
              </div>
            </div>

            <div style={{...styles.statCard, ...styles.statCardInfo}}>
              <div style={styles.statIcon}>📊</div>
              <div style={styles.statContent}>
                <div style={styles.statValue}>{stats.results_count}</div>
                <div style={styles.statLabel}>Analysis Results</div>
              </div>
            </div>
          </div>

          {/* Label Distribution */}
          {Object.keys(stats.labels).length > 0 && (
            <div style={styles.section}>
              <h2 style={styles.sectionTitle}>Label Distribution</h2>
              <div style={styles.labelGrid}>
                {Object.entries(stats.labels).map(([label, count]) => (
                  <div key={label} style={styles.labelCard}>
                    <div style={styles.labelName}>{label}</div>
                    <div style={styles.labelCount}>{count} samples</div>
                    <div style={styles.labelBar}>
                      <div 
                        style={{
                          ...styles.labelBarFill,
                          width: `${(count / stats.wsi_count) * 100}%`
                        }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Quick Actions */}
          <div style={styles.section}>
            <h2 style={styles.sectionTitle}>Quick Actions</h2>
            <div style={styles.actionsGrid}>
              <button 
                style={styles.actionButton}
                onClick={() => navigate('/task-setup')}
              >
                <div style={styles.actionIcon}>🚀</div>
                <div style={styles.actionText}>
                  <div style={styles.actionTitle}>New Task</div>
                  <div style={styles.actionDesc}>Start a new research task</div>
                </div>
              </button>

              <button 
                style={styles.actionButton}
                onClick={() => navigate('/wsi-list')}
              >
                <div style={styles.actionIcon}>📁</div>
                <div style={styles.actionText}>
                  <div style={styles.actionTitle}>Browse WSI</div>
                  <div style={styles.actionDesc}>View all WSI files</div>
                </div>
              </button>

              <button 
                style={styles.actionButton}
                onClick={() => navigate('/training-data-selection')}
              >
                <div style={styles.actionIcon}>🎯</div>
                <div style={styles.actionText}>
                  <div style={styles.actionTitle}>Select Data</div>
                  <div style={styles.actionDesc}>Choose training data</div>
                </div>
              </button>

              <button 
                style={styles.actionButton}
                onClick={() => navigate('/inference')}
              >
                <div style={styles.actionIcon}>🔍</div>
                <div style={styles.actionText}>
                  <div style={styles.actionTitle}>Inference</div>
                  <div style={styles.actionDesc}>Run model inference</div>
                </div>
              </button>
            </div>
          </div>

          {/* System Status */}
          <div style={styles.section}>
            <h2 style={styles.sectionTitle}>System Status</h2>
            <div style={styles.statusGrid}>
              <div style={styles.statusItem}>
                <div style={styles.statusDot} />
                <div style={styles.statusText}>Gateway Service: Online</div>
              </div>
              <div style={styles.statusItem}>
                <div style={styles.statusDot} />
                <div style={styles.statusText}>WSI Service: Online</div>
              </div>
              <div style={styles.statusItem}>
                <div style={styles.statusDot} />
                <div style={styles.statusText}>AI Service: Online</div>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    minHeight: '100vh',
    background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
    padding: '40px 20px',
  },
  header: {
    textAlign: 'center' as const,
    marginBottom: '40px',
  },
  title: {
    fontSize: '48px',
    fontWeight: 'bold',
    color: '#fff',
    margin: '0 0 10px 0',
    textShadow: '2px 2px 4px rgba(0,0,0,0.2)',
  },
  subtitle: {
    fontSize: '18px',
    color: 'rgba(255,255,255,0.9)',
    margin: 0,
  },
  loading: {
    textAlign: 'center' as const,
    color: '#fff',
    fontSize: '18px',
    padding: '40px',
  },
  error: {
    background: '#ff4444',
    color: '#fff',
    padding: '20px',
    borderRadius: '8px',
    margin: '20px auto',
    maxWidth: '600px',
    textAlign: 'center' as const,
  },
  statsGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))',
    gap: '20px',
    maxWidth: '1200px',
    margin: '0 auto 40px auto',
  },
  statCard: {
    background: '#fff',
    borderRadius: '12px',
    padding: '24px',
    display: 'flex',
    alignItems: 'center',
    gap: '16px',
    boxShadow: '0 4px 6px rgba(0,0,0,0.1)',
    transition: 'transform 0.2s, box-shadow 0.2s',
    cursor: 'default',
  },
  statCardPrimary: {
    borderLeft: '4px solid #667eea',
  },
  statCardSuccess: {
    borderLeft: '4px solid #48bb78',
  },
  statCardWarning: {
    borderLeft: '4px solid #ed8936',
  },
  statCardInfo: {
    borderLeft: '4px solid #4299e1',
  },
  statIcon: {
    fontSize: '40px',
  },
  statContent: {
    flex: 1,
  },
  statValue: {
    fontSize: '32px',
    fontWeight: 'bold',
    color: '#2d3748',
    lineHeight: 1,
  },
  statLabel: {
    fontSize: '14px',
    color: '#718096',
    marginTop: '4px',
  },
  section: {
    maxWidth: '1200px',
    margin: '0 auto 40px auto',
    background: '#fff',
    borderRadius: '12px',
    padding: '24px',
    boxShadow: '0 4px 6px rgba(0,0,0,0.1)',
  },
  sectionTitle: {
    fontSize: '24px',
    fontWeight: 'bold',
    color: '#2d3748',
    margin: '0 0 20px 0',
  },
  labelGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
    gap: '16px',
  },
  labelCard: {
    padding: '16px',
    background: '#f7fafc',
    borderRadius: '8px',
    border: '1px solid #e2e8f0',
  },
  labelName: {
    fontSize: '16px',
    fontWeight: '600',
    color: '#2d3748',
    marginBottom: '4px',
  },
  labelCount: {
    fontSize: '14px',
    color: '#718096',
    marginBottom: '8px',
  },
  labelBar: {
    height: '6px',
    background: '#e2e8f0',
    borderRadius: '3px',
    overflow: 'hidden',
  },
  labelBarFill: {
    height: '100%',
    background: 'linear-gradient(90deg, #667eea 0%, #764ba2 100%)',
    transition: 'width 0.3s ease',
  },
  actionsGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))',
    gap: '16px',
  },
  actionButton: {
    display: 'flex',
    alignItems: 'center',
    gap: '16px',
    padding: '20px',
    background: '#f7fafc',
    border: '2px solid #e2e8f0',
    borderRadius: '8px',
    cursor: 'pointer',
    transition: 'all 0.2s',
    textAlign: 'left' as const,
  },
  actionIcon: {
    fontSize: '32px',
  },
  actionText: {
    flex: 1,
  },
  actionTitle: {
    fontSize: '16px',
    fontWeight: '600',
    color: '#2d3748',
    marginBottom: '4px',
  },
  actionDesc: {
    fontSize: '14px',
    color: '#718096',
  },
  statusGrid: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '12px',
  },
  statusItem: {
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
  },
  statusDot: {
    width: '12px',
    height: '12px',
    borderRadius: '50%',
    background: '#48bb78',
    boxShadow: '0 0 8px rgba(72, 187, 120, 0.5)',
  },
  statusText: {
    fontSize: '16px',
    color: '#2d3748',
  },
}

