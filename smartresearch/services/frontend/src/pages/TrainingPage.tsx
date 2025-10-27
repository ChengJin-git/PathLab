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
    if (!taskDescription || selectedWSIs.length === 0) {
      navigate('/')
      return
    }

    let isCancelled = false

    // 模拟训练过程
    const simulateTraining = async () => {
      if (isCancelled) return

      // 准备阶段
      setStatus('preparing')
      addLog('正在准备训练环境...')
      await sleep(1000)
      if (isCancelled) return

      addLog(`加载 ${selectedWSIs.length} 个WSI文件...`)
      await sleep(1000)
      if (isCancelled) return

      addLog('初始化模型...')
      await sleep(1000)
      if (isCancelled) return

      // 训练阶段
      setStatus('training')
      addLog('开始训练...')

      for (let i = 0; i <= 100; i += 5) {
        if (isCancelled) return
        setProgress(i)
        if (i % 20 === 0) {
          addLog(`训练进度: ${i}% - Loss: ${(1.5 - i * 0.01).toFixed(3)}`)
        }
        await sleep(500)
      }

      if (isCancelled) return

      // 完成
      setStatus('completed')
      addLog('训练完成！')
      addLog('模型已保存')

      // 保存训练完成状态
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
    navigate('/inference')
  }

  const handleBack = () => {
    navigate('/training-data-selection')
  }

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <h1 style={styles.title}>模型训练</h1>
        <p style={styles.subtitle}>
          任务: {taskDescription}
        </p>
        <p style={styles.info}>
          训练数据: {selectedWSIs.length} 个WSI
        </p>
      </div>

      <div style={styles.content}>
        {/* 进度卡片 */}
        <div style={styles.card}>
          <h3 style={styles.cardTitle}>训练进度</h3>
          <div style={styles.progressContainer}>
            <div style={styles.progressBar}>
              <div style={{...styles.progressFill, width: `${progress}%`}} />
            </div>
            <div style={styles.progressText}>{progress}%</div>
          </div>
          
          <div style={styles.statusContainer}>
            <div style={styles.statusItem}>
              <span style={styles.statusLabel}>状态:</span>
              <span style={{
                ...styles.statusBadge,
                ...(status === 'preparing' ? styles.statusPreparing :
                    status === 'training' ? styles.statusTraining :
                    styles.statusCompleted)
              }}>
                {status === 'preparing' ? '准备中' :
                 status === 'training' ? '训练中' :
                 '已完成'}
              </span>
            </div>
          </div>
        </div>

        {/* 训练日志 */}
        <div style={styles.card}>
          <h3 style={styles.cardTitle}>训练日志</h3>
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
          ← 返回
        </button>
        <button
          onClick={handleNext}
          disabled={status !== 'completed'}
          style={{
            ...styles.button,
            ...(status === 'completed' ? styles.buttonPrimary : styles.buttonDisabled)
          }}
        >
          查看推理结果 →
        </button>
      </div>

      <div style={styles.placeholder}>
        <div style={{...styles.placeholderBox, ...styles.placeholderActive}}>
          <p style={styles.placeholderText}>✓ 任务设定</p>
        </div>
        <div style={{...styles.placeholderBox, ...styles.placeholderActive}}>
          <p style={styles.placeholderText}>✓ 选择训练数据</p>
        </div>
        <div style={{...styles.placeholderBox, ...styles.placeholderActive}}>
          <p style={styles.placeholderText}>🚀 模型训练</p>
        </div>
        <div style={styles.placeholderBox}>
          <p style={styles.placeholderText}>📊 推理结果</p>
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
  header: {
    background: 'white',
    padding: 24,
    borderRadius: 8,
    marginBottom: 20,
    boxShadow: '0 1px 3px rgba(0,0,0,0.1)'
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

