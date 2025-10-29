import React, { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

export default function TrainingPage() {
  const navigate = useNavigate()
  const [progress, setProgress] = useState(0)
  const [status, setStatus] = useState<'preparing' | 'training' | 'completed'>('preparing')
  const [logs, setLogs] = useState<string[]>([])
  
  const taskDescription = sessionStorage.getItem('taskDescription') || ''
  const selectedWSIs = JSON.parse(sessionStorage.getItem('selectedTrainingWSIs') || '[]')

  useEffect(() => {
    // Allow page to load even without data, but don't start training
    if (!taskDescription || selectedWSIs.length === 0) {
      return
    }

    let isCancelled = false

    // Simulate training process
    const simulateTraining = async () => {
      if (isCancelled) return

      // Preparation phase
      setStatus('preparing')
      addLog('Preparing training environment...')
      await sleep(1000)
      if (isCancelled) return

      addLog(`Loading ${selectedWSIs.length} WSI files...`)
      await sleep(1000)
      if (isCancelled) return

      addLog('Initializing model...')
      await sleep(1000)
      if (isCancelled) return

      // Training phase
      setStatus('training')
      addLog('Starting training...')

      for (let i = 0; i <= 100; i += 5) {
        if (isCancelled) return
        setProgress(i)
        if (i % 20 === 0) {
          addLog(`Training progress: ${i}% - Loss: ${(1.5 - i * 0.01).toFixed(3)}`)
        }
        await sleep(500)
      }

      if (isCancelled) return

      // Completion
      setStatus('completed')
      addLog('Training completed!')
      addLog('Model saved')

      // Save training completion status
      sessionStorage.setItem('trainingCompleted', 'true')
    }

    simulateTraining()

    return () => {
      isCancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const addLog = (message: string) => {
    const timestamp = new Date().toLocaleTimeString()
    setLogs(prev => [...prev, `[${timestamp}] ${message}`])
  }

  const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

  const handleNext = () => {
    navigate('/wsi-list')
  }

  const handleBack = () => {
    navigate('/training-data-selection')
  }

  // Show warning if no data
  if (!taskDescription || selectedWSIs.length === 0) {
    return (
      <div style={styles.container}>
        <div style={styles.warningCard}>
          <h2 style={styles.warningTitle}>⚠️ Training Not Ready</h2>
          <p style={styles.warningText}>
            You need to complete the previous steps before starting training:
          </p>
          <ol style={styles.warningList}>
            <li>Go to <a href="/SmartResearch/task-setup" style={styles.link}>Task Setup</a> to describe your task</li>
            <li>Go to <a href="/SmartResearch/training-data-selection" style={styles.link}>Training Data Selection</a> to select WSI files</li>
          </ol>
        </div>
      </div>
    )
  }

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <button onClick={() => navigate('/')} style={styles.homeButton}>
          ← Dashboard
        </button>
        <h1 style={styles.title}>Model Training</h1>
        <p style={styles.subtitle}>
          Task: {taskDescription}
        </p>
        <p style={styles.info}>
          Training Data: {selectedWSIs.length} WSI files
        </p>
      </div>

      <div style={styles.content}>
        {/* Progress Card */}
        <div style={styles.card}>
          <h3 style={styles.cardTitle}>Training Progress</h3>
          <div style={styles.progressContainer}>
            <div style={styles.progressBar}>
              <div style={{...styles.progressFill, width: `${progress}%`}} />
            </div>
            <div style={styles.progressText}>{progress}%</div>
          </div>

          <div style={styles.statusContainer}>
            <div style={styles.statusItem}>
              <span style={styles.statusLabel}>Status:</span>
              <span style={{
                ...styles.statusBadge,
                ...(status === 'preparing' ? styles.statusPreparing :
                    status === 'training' ? styles.statusTraining :
                    styles.statusCompleted)
              }}>
                {status === 'preparing' ? 'Preparing' :
                 status === 'training' ? 'Training' :
                 'Completed'}
              </span>
            </div>
          </div>
        </div>

        {/* Training Logs */}
        <div style={styles.card}>
          <h3 style={styles.cardTitle}>Training Logs</h3>
          <div style={styles.logContainer}>
            {logs.map((log, idx) => (
              <div key={idx} style={styles.logLine}>
                {log}
              </div>
            ))}
          </div>
        </div>
      </div>

      <div style={styles.buttonGroup}>
        <button
          onClick={handleBack}
          disabled={status === 'training'}
          style={{
            ...styles.buttonSecondary,
            ...(status === 'training' ? styles.buttonDisabled : {})
          }}
        >
          ← Back
        </button>
        <button
          onClick={handleNext}
          disabled={status !== 'completed'}
          style={{
            ...styles.button,
            ...(status === 'completed' ? styles.buttonPrimary : styles.buttonDisabled)
          }}
        >
          View Results in WSI Browser →
        </button>
      </div>

      <div style={styles.placeholder}>
        <div style={{...styles.placeholderBox, ...styles.placeholderActive}}>
          <p style={styles.placeholderText}>✓ Task Setup</p>
        </div>
        <div style={{...styles.placeholderBox, ...styles.placeholderActive}}>
          <p style={styles.placeholderText}>✓ Select Training Data</p>
        </div>
        <div style={{...styles.placeholderBox, ...styles.placeholderActive}}>
          <p style={styles.placeholderText}>🚀 Model Training</p>
        </div>
        <div style={styles.placeholderBox}>
          <p style={styles.placeholderText}>📊 Inference Results</p>
        </div>
      </div>
    </div>
  )
}

const styles = {
  container: {
    minHeight: '100vh',
    background: '#f6f8fa',
    padding: 20
  },
  warningCard: {
    background: 'white',
    padding: 40,
    borderRadius: 12,
    maxWidth: 600,
    margin: '40px auto',
    boxShadow: '0 4px 12px rgba(0,0,0,0.1)',
    border: '2px solid #ffc107'
  },
  warningTitle: {
    margin: '0 0 16px 0',
    fontSize: 24,
    color: '#856404'
  },
  warningText: {
    margin: '0 0 16px 0',
    fontSize: 16,
    color: '#666'
  },
  warningList: {
    margin: '16px 0',
    paddingLeft: 24,
    fontSize: 16,
    color: '#333',
    lineHeight: 1.8
  },
  link: {
    color: '#0969da',
    textDecoration: 'underline'
  },
  header: {
    background: 'white',
    padding: 24,
    borderRadius: 8,
    marginBottom: 20,
    boxShadow: '0 1px 3px rgba(0,0,0,0.1)'
  },
  homeButton: {
    background: 'transparent',
    border: 'none',
    color: '#667eea',
    fontSize: 14,
    fontWeight: 'bold' as const,
    cursor: 'pointer',
    padding: '8px 0',
    marginBottom: 12,
    display: 'inline-block'
  },
  title: {
    margin: 0,
    fontSize: 28,
    fontWeight: 'bold' as const,
    color: '#333'
  },
  subtitle: {
    margin: '8px 0 0 0',
    fontSize: 14,
    color: '#666'
  },
  info: {
    margin: '12px 0 0 0',
    fontSize: 14,
    color: '#0969da',
    fontWeight: 'bold' as const
  },
  content: {
    display: 'grid',
    gap: 20,
    gridTemplateColumns: '1fr 1fr'
  },
  card: {
    background: 'white',
    padding: 24,
    borderRadius: 8,
    boxShadow: '0 1px 3px rgba(0,0,0,0.1)'
  },
  cardTitle: {
    margin: '0 0 16px 0',
    fontSize: 18,
    fontWeight: 'bold' as const,
    color: '#333'
  },
  progressContainer: {
    marginBottom: 24
  },
  progressBar: {
    width: '100%',
    height: 24,
    background: '#e1e4e8',
    borderRadius: 12,
    overflow: 'hidden' as const,
    marginBottom: 8
  },
  progressFill: {
    height: '100%',
    background: 'linear-gradient(90deg, #667eea 0%, #764ba2 100%)',
    transition: 'width 0.3s ease'
  },
  progressText: {
    textAlign: 'center' as const,
    fontSize: 16,
    fontWeight: 'bold' as const,
    color: '#333'
  },
  statusContainer: {
    marginTop: 16
  },
  statusItem: {
    display: 'flex',
    alignItems: 'center',
    gap: 12
  },
  statusLabel: {
    fontSize: 14,
    fontWeight: 'bold' as const,
    color: '#666'
  },
  statusBadge: {
    padding: '4px 12px',
    borderRadius: 12,
    fontSize: 12,
    fontWeight: 'bold' as const
  },
  statusPreparing: {
    background: '#ffc107',
    color: '#000'
  },
  statusTraining: {
    background: '#0969da',
    color: 'white'
  },
  statusCompleted: {
    background: '#2da44e',
    color: 'white'
  },
  logContainer: {
    background: '#1a1a1a',
    color: '#00ff00',
    padding: 16,
    borderRadius: 6,
    fontFamily: 'monospace',
    fontSize: 12,
    maxHeight: 400,
    overflowY: 'auto' as const
  },
  logLine: {
    marginBottom: 4,
    lineHeight: 1.5
  },
  buttonGroup: {
    display: 'flex',
    justifyContent: 'space-between',
    marginTop: 20,
    gap: 12
  },
  button: {
    padding: '12px 32px',
    fontSize: 16,
    fontWeight: 'bold' as const,
    border: 'none',
    borderRadius: 6,
    cursor: 'pointer',
    transition: 'all 0.2s'
  },
  buttonPrimary: {
    background: '#667eea',
    color: 'white'
  },
  buttonSecondary: {
    padding: '12px 32px',
    fontSize: 16,
    fontWeight: 'bold' as const,
    border: '2px solid #d0d7de',
    borderRadius: 6,
    cursor: 'pointer',
    background: 'white',
    color: '#333'
  },
  buttonDisabled: {
    background: '#e1e4e8',
    color: '#999',
    cursor: 'not-allowed',
    border: 'none'
  },
  placeholder: {
    display: 'flex',
    gap: 12,
    marginTop: 24
  },
  placeholderBox: {
    flex: 1,
    padding: 16,
    background: 'white',
    borderRadius: 6,
    border: '2px dashed #d0d7de',
    textAlign: 'center' as const
  },
  placeholderActive: {
    background: '#e6f3ff',
    borderColor: '#0969da',
    borderStyle: 'solid' as const
  },
  placeholderText: {
    margin: 0,
    fontSize: 12,
    color: '#666'
  }
}

