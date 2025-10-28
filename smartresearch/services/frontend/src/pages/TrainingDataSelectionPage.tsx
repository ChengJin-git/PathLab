import React, { useEffect, useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchWSIList, uploadWSIFile, uploadWSIByPath } from '../api'

export default function TrainingDataSelectionPage() {
  const navigate = useNavigate()
  const [items, setItems] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | undefined>()
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState<string>('')
  const [showPathDialog, setShowPathDialog] = useState(false)
  const [pathInput, setPathInput] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)
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

  const refreshWSIList = async () => {
    setLoading(true)
    try {
      const data = await fetchWSIList()
      setItems(data.items || [])
      setError(undefined)
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }

  const handleFileUpload = async (files: FileList | null) => {
    if (!files || files.length === 0) return

    setUploading(true)
    setUploadProgress(`Uploading ${files.length} file(s)...`)

    try {
      let successCount = 0
      let failCount = 0

      for (let i = 0; i < files.length; i++) {
        const file = files[i]
        setUploadProgress(`Uploading ${i + 1}/${files.length}: ${file.name}`)

        try {
          await uploadWSIFile(file)
          successCount++
        } catch (err) {
          console.error(`Failed to upload ${file.name}:`, err)
          failCount++
        }
      }

      setUploadProgress(`Upload complete! Success: ${successCount}, Failed: ${failCount}`)

      // Refresh the list after upload
      await refreshWSIList()

      // Clear progress message after 3 seconds
      setTimeout(() => {
        setUploadProgress('')
      }, 3000)
    } catch (err) {
      setError(`Upload failed: ${err}`)
    } finally {
      setUploading(false)
      // Reset file input
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    }
  }

  const handleFileClick = () => {
    if (fileInputRef.current) {
      fileInputRef.current.multiple = true
      fileInputRef.current.click()
    }
  }

  const handlePathUpload = async () => {
    if (!pathInput.trim()) {
      alert('Please enter file path')
      return
    }

    setUploading(true)
    setUploadProgress('Registering WSI...')

    try {
      await uploadWSIByPath(pathInput.trim())
      setUploadProgress('Registration successful!')
      setShowPathDialog(false)
      setPathInput('')

      // Refresh the list
      await refreshWSIList()

      // Clear progress message after 3 seconds
      setTimeout(() => {
        setUploadProgress('')
      }, 3000)
    } catch (err) {
      setError(`Registration failed: ${err}`)
    } finally {
      setUploading(false)
    }
  }

  if (loading) return <div style={styles.container}>Loading...</div>
  if (error) return <div style={styles.container}>Error: {error}</div>

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <h1 style={styles.title}>Select Training Data</h1>
        <p style={styles.subtitle}>
          Task: {taskDescription}
        </p>
        <p style={styles.info}>
          Selected {selectedIds.size} WSI(s) for training
        </p>
      </div>

      {/* Upload Section */}
      <div style={styles.uploadSection}>
        <div style={styles.uploadButtons}>
          <button
            onClick={handleFileClick}
            disabled={uploading}
            style={{...styles.uploadButton, ...styles.uploadButtonPrimary}}
          >
            📁 Upload WSI Files
          </button>
          <button
            onClick={() => setShowPathDialog(true)}
            disabled={uploading}
            style={{...styles.uploadButton, ...styles.uploadButtonSecondary}}
          >
            🔗 Upload by Path
          </button>
        </div>

        {uploadProgress && (
          <div style={styles.uploadProgress}>
            {uploadProgress}
          </div>
        )}

        {/* Hidden file input */}
        <input
          ref={fileInputRef}
          type="file"
          accept=".svs,.svslide,.ndpi,.scn,.mrxs,.bif,.tif,.tiff,.vsi,.vms,.vmu,.kfb,.sdpc,.TMAP,.mds,.mdsx,.tron,.isyntax"
          multiple
          style={{ display: 'none' }}
          onChange={(e) => handleFileUpload(e.target.files)}
        />
      </div>

      {/* Path Upload Dialog */}
      {showPathDialog && (
        <div style={styles.dialogOverlay}>
          <div style={styles.dialog}>
            <h3 style={styles.dialogTitle}>Upload by Path</h3>
            <p style={styles.dialogSubtitle}>
              Enter the full path to the WSI file on the server
            </p>
            <input
              type="text"
              value={pathInput}
              onChange={(e) => setPathInput(e.target.value)}
              placeholder="/path/to/wsi/file.svs"
              style={styles.pathInput}
              autoFocus
            />
            <div style={styles.dialogButtons}>
              <button
                onClick={() => {
                  setShowPathDialog(false)
                  setPathInput('')
                }}
                style={styles.dialogButtonCancel}
              >
                Cancel
              </button>
              <button
                onClick={handlePathUpload}
                disabled={!pathInput.trim() || uploading}
                style={{
                  ...styles.dialogButtonConfirm,
                  ...((!pathInput.trim() || uploading) ? styles.buttonDisabled : {})
                }}
              >
                Confirm
              </button>
            </div>
          </div>
        </div>
      )}

      {items.length === 0 ? (
        <div style={styles.emptyState}>
          <p>No WSI data available. Please upload data first.</p>
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
                <th style={styles.th}>Status</th>
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
                    <span style={styles.badge}>Available</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div style={styles.buttonGroup}>
        <button onClick={handleBack} style={styles.buttonSecondary}>
          ← Back
        </button>
        <button
          onClick={handleNext}
          disabled={selectedIds.size === 0}
          style={{
            ...styles.button,
            ...(selectedIds.size > 0 ? styles.buttonPrimary : styles.buttonDisabled)
          }}
        >
          Start Training →
        </button>
      </div>

      <div style={styles.placeholder}>
        <div style={{...styles.placeholderBox, ...styles.placeholderActive}}>
          <p style={styles.placeholderText}>✓ Task Setup</p>
        </div>
        <div style={{...styles.placeholderBox, ...styles.placeholderActive}}>
          <p style={styles.placeholderText}>📋 Select Training Data</p>
        </div>
        <div style={styles.placeholderBox}>
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
  },
  uploadSection: {
    background: 'white',
    padding: 20,
    borderRadius: 8,
    marginBottom: 20,
    boxShadow: '0 1px 3px rgba(0,0,0,0.1)'
  },
  uploadButtons: {
    display: 'flex',
    gap: 12,
    marginBottom: 12
  },
  uploadButton: {
    padding: '10px 20px',
    fontSize: 14,
    fontWeight: 'bold' as const,
    border: 'none',
    borderRadius: 6,
    cursor: 'pointer',
    transition: 'all 0.2s'
  },
  uploadButtonPrimary: {
    background: '#2da44e',
    color: 'white'
  },
  uploadButtonSecondary: {
    background: 'white',
    color: '#333',
    border: '2px solid #d0d7de'
  },
  uploadProgress: {
    padding: 12,
    background: '#e6f3ff',
    borderRadius: 6,
    fontSize: 14,
    color: '#0969da',
    textAlign: 'center' as const
  },
  dialogOverlay: {
    position: 'fixed' as const,
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    background: 'rgba(0,0,0,0.5)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 1000
  },
  dialog: {
    background: 'white',
    padding: 24,
    borderRadius: 8,
    minWidth: 400,
    maxWidth: 600,
    boxShadow: '0 4px 12px rgba(0,0,0,0.3)'
  },
  dialogTitle: {
    margin: '0 0 8px 0',
    fontSize: 20,
    fontWeight: 'bold' as const,
    color: '#333'
  },
  dialogSubtitle: {
    margin: '0 0 16px 0',
    fontSize: 14,
    color: '#666'
  },
  pathInput: {
    width: '100%',
    padding: 12,
    fontSize: 14,
    border: '2px solid #d0d7de',
    borderRadius: 6,
    marginBottom: 16,
    boxSizing: 'border-box' as const
  },
  dialogButtons: {
    display: 'flex',
    gap: 12,
    justifyContent: 'flex-end'
  },
  dialogButtonCancel: {
    padding: '10px 20px',
    fontSize: 14,
    fontWeight: 'bold' as const,
    border: '2px solid #d0d7de',
    borderRadius: 6,
    cursor: 'pointer',
    background: 'white',
    color: '#333'
  },
  dialogButtonConfirm: {
    padding: '10px 20px',
    fontSize: 14,
    fontWeight: 'bold' as const,
    border: 'none',
    borderRadius: 6,
    cursor: 'pointer',
    background: '#2da44e',
    color: 'white'
  }
}

