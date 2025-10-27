import React, { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchWSIList } from '../api'

export default function TrainingDataSelectionPage() {
  const navigate = useNavigate()
  const [items, setItems] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | undefined>()
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const taskDescription = sessionStorage.getItem('taskDescription') || ''

  useEffect(() => {
    if (!taskDescription) {
      navigate('/')
      return
    }
    
    fetchWSIList()
      .then((d) => setItems(d.items || []))
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false))
  }, [taskDescription, navigate])

  const toggleSelection = (wsi_id: string) => {
    const newSelected = new Set(selectedIds)
    if (newSelected.has(wsi_id)) {
      newSelected.delete(wsi_id)
    } else {
      newSelected.add(wsi_id)
    }
    setSelectedIds(newSelected)
  }

  const handleNext = () => {
    if (selectedIds.size > 0) {
      sessionStorage.setItem('selectedTrainingWSIs', JSON.stringify(Array.from(selectedIds)))
      navigate('/training')
    }
  }

  const handleBack = () => {
    navigate('/')
  }

  if (loading) return <div style={styles.container}>Loading...</div>
  if (error) return <div style={styles.container}>Error: {error}</div>

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <h1 style={styles.title}>选择训练数据</h1>
        <p style={styles.subtitle}>
          任务: {taskDescription}
        </p>
        <p style={styles.info}>
          已选择 {selectedIds.size} 个WSI用于训练
        </p>
      </div>

      {items.length === 0 ? (
        <div style={styles.emptyState}>
          <p>暂无WSI数据，请先导入数据</p>
        </div>
      ) : (
        <div style={styles.tableContainer}>
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>
                  <input
                    type="checkbox"
                    checked={selectedIds.size === items.length && items.length > 0}
                    onChange={(e) => {
                      if (e.target.checked) {
                        setSelectedIds(new Set(items.map(it => it.wsi_id)))
                      } else {
                        setSelectedIds(new Set())
                      }
                    }}
                  />
                </th>
                <th style={styles.th}>WSI ID</th>
                <th style={styles.th}>Label</th>
                <th style={styles.th}>状态</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => (
                <tr
                  key={it.wsi_id}
                  style={{
                    ...styles.tr,
                    ...(selectedIds.has(it.wsi_id) ? styles.trSelected : {})
                  }}
                  onClick={() => toggleSelection(it.wsi_id)}
                >
                  <td style={styles.td}>
                    <input
                      type="checkbox"
                      checked={selectedIds.has(it.wsi_id)}
                      onChange={() => toggleSelection(it.wsi_id)}
                      onClick={(e) => e.stopPropagation()}
                    />
                  </td>
                  <td style={styles.td}>{it.wsi_id}</td>
                  <td style={styles.td}>{it.label || '-'}</td>
                  <td style={styles.td}>
                    <span style={styles.badge}>可用</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div style={styles.buttonGroup}>
        <button onClick={handleBack} style={styles.buttonSecondary}>
          ← 返回
        </button>
        <button
          onClick={handleNext}
          disabled={selectedIds.size === 0}
          style={{
            ...styles.button,
            ...(selectedIds.size > 0 ? styles.buttonPrimary : styles.buttonDisabled)
          }}
        >
          开始训练 →
        </button>
      </div>

      <div style={styles.placeholder}>
        <div style={{...styles.placeholderBox, ...styles.placeholderActive}}>
          <p style={styles.placeholderText}>✓ 任务设定</p>
        </div>
        <div style={{...styles.placeholderBox, ...styles.placeholderActive}}>
          <p style={styles.placeholderText}>📋 选择训练数据</p>
        </div>
        <div style={styles.placeholderBox}>
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
  emptyState: {
    background: 'white',
    padding: 40,
    borderRadius: 8,
    textAlign: 'center' as const,
    color: '#666'
  },
  tableContainer: {
    background: 'white',
    borderRadius: 8,
    overflow: 'hidden',
    boxShadow: '0 1px 3px rgba(0,0,0,0.1)'
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
    fontWeight: 'bold' as const
  },
  tr: {
    cursor: 'pointer',
    transition: 'background 0.2s'
  },
  trSelected: {
    background: '#e6f3ff'
  },
  td: {
    border: '1px solid #ddd',
    padding: 12
  },
  badge: {
    padding: '4px 8px',
    background: '#2da44e',
    color: 'white',
    fontSize: 12,
    borderRadius: 4,
    fontWeight: 'bold' as const
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
    cursor: 'not-allowed'
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

