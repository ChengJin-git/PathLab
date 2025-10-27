import React, { useEffect, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { fetchWSIList } from '../api'

export default function InferencePage() {
  const navigate = useNavigate()
  const [items, setItems] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [inferenceResults, setInferenceResults] = useState<Map<string, any>>(new Map())
  
  const taskDescription = sessionStorage.getItem('taskDescription') || ''
  const trainingCompleted = sessionStorage.getItem('trainingCompleted')

  useEffect(() => {
    if (!taskDescription || !trainingCompleted) {
      navigate('/')
      return
    }

    // 加载WSI列表
    fetchWSIList()
      .then((d) => {
        setItems(d.items || [])
        // 模拟推理结果
        simulateInference(d.items || [])
      })
      .catch((e) => console.error(e))
      .finally(() => setLoading(false))
  }, [taskDescription, trainingCompleted, navigate])

  const simulateInference = (wsiList: any[]) => {
    const results = new Map()
    const classes = ['LUAD', 'LUSC', 'Normal']
    
    wsiList.forEach(wsi => {
      const pred = classes[Math.floor(Math.random() * classes.length)]
      const probs: any = {}
      
      // 生成随机概率
      classes.forEach(cls => {
        probs[cls] = Math.random()
      })
      
      // 归一化
      const total = Object.values(probs).reduce((a: any, b: any) => a + b, 0)
      Object.keys(probs).forEach(cls => {
        probs[cls] = probs[cls] / total
      })
      
      // 提高预测类的概率
      probs[pred] = Math.max(probs[pred], 0.6)
      
      results.set(wsi.wsi_id, {
        pred,
        probs,
        confidence: probs[pred]
      })
    })
    
    setInferenceResults(results)
  }

  const handleGoToWSIList = () => {
    navigate('/wsi-list')
  }

  const handleRestart = () => {
    sessionStorage.clear()
    navigate('/')
  }

  if (loading) return <div style={styles.container}>Loading...</div>

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <h1 style={styles.title}>推理结果</h1>
        <p style={styles.subtitle}>
          任务: {taskDescription}
        </p>
        <p style={styles.info}>
          共推理 {items.length} 个WSI
        </p>
      </div>

      <div style={styles.content}>
        {items.length === 0 ? (
          <div style={styles.emptyState}>
            <p>暂无WSI数据</p>
          </div>
        ) : (
          <div style={styles.tableContainer}>
            <table style={styles.table}>
              <thead>
                <tr>
                  <th style={styles.th}>WSI ID</th>
                  <th style={styles.th}>真实标签</th>
                  <th style={styles.th}>预测结果</th>
                  <th style={styles.th}>置信度</th>
                  <th style={styles.th}>概率分布</th>
                  <th style={styles.th}>操作</th>
                </tr>
              </thead>
              <tbody>
                {items.map((it) => {
                  const result = inferenceResults.get(it.wsi_id)
                  if (!result) return null
                  
                  const isCorrect = it.label === result.pred
                  
                  return (
                    <tr key={it.wsi_id}>
                      <td style={styles.td}>{it.wsi_id}</td>
                      <td style={styles.td}>{it.label || '-'}</td>
                      <td style={styles.td}>
                        <span style={{
                          ...styles.predBadge,
                          ...(isCorrect ? styles.predCorrect : styles.predIncorrect)
                        }}>
                          {result.pred}
                        </span>
                      </td>
                      <td style={styles.td}>
                        {(result.confidence * 100).toFixed(1)}%
                      </td>
                      <td style={styles.td}>
                        <div style={styles.probContainer}>
                          {Object.entries(result.probs)
                            .sort((a: any, b: any) => b[1] - a[1])
                            .map(([cls, prob]: any) => (
                              <div key={cls} style={styles.probRow}>
                                <span style={styles.probLabel}>{cls}:</span>
                                <div style={styles.probBar}>
                                  <div style={{
                                    ...styles.probFill,
                                    width: `${prob * 100}%`
                                  }} />
                                </div>
                                <span style={styles.probValue}>
                                  {(prob * 100).toFixed(1)}%
                                </span>
                              </div>
                            ))}
                        </div>
                      </td>
                      <td style={styles.td}>
                        <Link to={`/wsi/${encodeURIComponent(it.wsi_id)}`}>
                          <button style={styles.viewButton}>查看</button>
                        </Link>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div style={styles.buttonGroup}>
        <button onClick={handleRestart} style={styles.buttonSecondary}>
          ← 重新开始
        </button>
        <button onClick={handleGoToWSIList} style={styles.buttonPrimary}>
          进入WSI列表 →
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
          <p style={styles.placeholderText}>✓ 模型训练</p>
        </div>
        <div style={{...styles.placeholderBox, ...styles.placeholderActive}}>
          <p style={styles.placeholderText}>✓ 推理结果</p>
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
    background: 'white',
    borderRadius: 8,
    overflow: 'hidden',
    boxShadow: '0 1px 3px rgba(0,0,0,0.1)'
  },
  emptyState: {
    padding: 40,
    textAlign: 'center' as const,
    color: '#666'
  },
  tableContainer: {
    overflowX: 'auto' as const
  },
  table: {
    width: '100%',
    borderCollapse: 'collapse' as const
  },
  th: {
    border: '1px solid #ddd',
    padding: 12,
    background: '#f6f8fa',
    textAlign: 'left' as const,
    fontWeight: 'bold' as const,
    fontSize: 14
  },
  td: {
    border: '1px solid #ddd',
    padding: 12,
    fontSize: 14
  },
  predBadge: {
    padding: '4px 12px',
    borderRadius: 12,
    fontSize: 12,
    fontWeight: 'bold' as const,
    display: 'inline-block'
  },
  predCorrect: {
    background: '#2da44e',
    color: 'white'
  },
  predIncorrect: {
    background: '#cf222e',
    color: 'white'
  },
  probContainer: {
    minWidth: 200
  },
  probRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    marginBottom: 4
  },
  probLabel: {
    fontSize: 11,
    fontWeight: 'bold' as const,
    width: 50
  },
  probBar: {
    flex: 1,
    height: 12,
    background: '#e1e4e8',
    borderRadius: 6,
    overflow: 'hidden' as const
  },
  probFill: {
    height: '100%',
    background: '#0969da',
    transition: 'width 0.3s'
  },
  probValue: {
    fontSize: 11,
    width: 45,
    textAlign: 'right' as const
  },
  viewButton: {
    padding: '6px 12px',
    cursor: 'pointer',
    background: '#0969da',
    color: 'white',
    border: 'none',
    borderRadius: 4,
    fontSize: 12,
    fontWeight: 'bold' as const
  },
  buttonGroup: {
    display: 'flex',
    justifyContent: 'space-between',
    marginTop: 20,
    gap: 12
  },
  buttonPrimary: {
    padding: '12px 32px',
    fontSize: 16,
    fontWeight: 'bold' as const,
    border: 'none',
    borderRadius: 6,
    cursor: 'pointer',
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

