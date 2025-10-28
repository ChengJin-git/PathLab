import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'

// Available models (placeholder)
const AVAILABLE_MODELS = [
  { id: 'resnet50', name: 'ResNet50', description: 'ImageNet pretrained feature extractor' },
  { id: 'vit_base', name: 'ViT-Base', description: 'Vision Transformer base model' },
  { id: 'ctranspath', name: 'CTransPath', description: 'Pathology-specific transformer' },
  { id: 'uni', name: 'UNI', description: 'Universal pathology foundation model' },
]

export default function TaskSetupPage() {
  const navigate = useNavigate()
  const [taskDescription, setTaskDescription] = useState('')
  const [selectedModels, setSelectedModels] = useState<string[]>(['resnet50']) // Default selection

  const handleModelToggle = (modelId: string) => {
    setSelectedModels(prev =>
      prev.includes(modelId)
        ? prev.filter(id => id !== modelId)
        : [...prev, modelId]
    )
  }

  const handleNext = () => {
    if (taskDescription.trim() && selectedModels.length > 0) {
      sessionStorage.setItem('taskDescription', taskDescription)
      sessionStorage.setItem('selectedModels', JSON.stringify(selectedModels))
      navigate('/training-data-selection')
    }
  }

  return (
    <div style={styles.container}>
      <div style={styles.card}>
        <div style={styles.header}>
          <button onClick={() => navigate('/')} style={styles.backButton}>
            ← Dashboard
          </button>
          <div>
            <h1 style={styles.title}>Task Setup</h1>
            <p style={styles.subtitle}>Describe your research task and select models</p>
          </div>
        </div>
        
        <div style={styles.formGroup}>
          <label style={styles.label}>Task Description</label>
          <textarea
            style={styles.textarea}
            value={taskDescription}
            onChange={(e) => setTaskDescription(e.target.value)}
            placeholder="e.g., Classify lung cancer pathology slides into LUAD, LUSC, and Normal tissue..."
            rows={6}
          />
        </div>

        <div style={styles.formGroup}>
          <label style={styles.label}>Select Models (Placeholder)</label>
          <p style={styles.hint}>Choose one or more feature extraction models for training</p>
          <div style={styles.modelGrid}>
            {AVAILABLE_MODELS.map(model => (
              <div
                key={model.id}
                onClick={() => handleModelToggle(model.id)}
                style={{
                  ...styles.modelCard,
                  ...(selectedModels.includes(model.id) ? styles.modelCardSelected : {})
                }}
              >
                <div style={styles.checkboxContainer}>
                  <input
                    type="checkbox"
                    checked={selectedModels.includes(model.id)}
                    onChange={() => {}} // Handled by parent div onClick
                    style={styles.checkbox}
                  />
                  <span style={styles.modelName}>{model.name}</span>
                </div>
                <p style={styles.modelDescription}>{model.description}</p>
              </div>
            ))}
          </div>
        </div>

        <div style={styles.buttonGroup}>
          <button
            onClick={handleNext}
            disabled={!taskDescription.trim() || selectedModels.length === 0}
            style={{
              ...styles.button,
              ...(taskDescription.trim() && selectedModels.length > 0 ? styles.buttonPrimary : styles.buttonDisabled)
            }}
          >
            Next →
          </button>
        </div>

        <div style={styles.placeholder}>
          <div style={{...styles.placeholderBox, ...styles.placeholderActive}}>
            <p style={styles.placeholderText}>📋 Task Setup</p>
          </div>
          <div style={styles.placeholderBox}>
            <p style={styles.placeholderText}>🔍 Select Training Data</p>
          </div>
          <div style={styles.placeholderBox}>
            <p style={styles.placeholderText}>🚀 Model Training</p>
          </div>
          <div style={styles.placeholderBox}>
            <p style={styles.placeholderText}>📊 Inference Results</p>
          </div>
        </div>
      </div>
    </div>
  )
}

const styles = {
  container: {
    minHeight: '100vh',
    background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 20
  },
  card: {
    background: 'white',
    borderRadius: 12,
    padding: 40,
    maxWidth: 800,
    width: '100%',
    boxShadow: '0 10px 40px rgba(0,0,0,0.2)'
  },
  header: {
    marginBottom: 32
  },
  backButton: {
    background: 'transparent',
    border: 'none',
    color: '#667eea',
    fontSize: 14,
    fontWeight: 'bold' as const,
    cursor: 'pointer',
    padding: '8px 0',
    marginBottom: 16,
    display: 'inline-block'
  },
  title: {
    margin: 0,
    fontSize: 32,
    fontWeight: 'bold' as const,
    color: '#333',
    marginBottom: 8
  },
  subtitle: {
    margin: 0,
    fontSize: 16,
    color: '#666'
  },
  formGroup: {
    marginBottom: 24
  },
  label: {
    display: 'block',
    fontSize: 14,
    fontWeight: 'bold' as const,
    color: '#333',
    marginBottom: 8
  },
  hint: {
    margin: '0 0 12px 0',
    fontSize: 13,
    color: '#666',
    fontStyle: 'italic' as const
  },
  textarea: {
    width: '100%',
    padding: 12,
    fontSize: 14,
    border: '2px solid #e1e4e8',
    borderRadius: 6,
    fontFamily: 'inherit',
    resize: 'vertical' as const,
    boxSizing: 'border-box' as const,
    outline: 'none',
    transition: 'border-color 0.2s'
  },
  modelGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(2, 1fr)',
    gap: 12
  },
  modelCard: {
    padding: 16,
    border: '2px solid #e1e4e8',
    borderRadius: 8,
    cursor: 'pointer',
    transition: 'all 0.2s',
    background: 'white'
  },
  modelCardSelected: {
    borderColor: '#667eea',
    background: '#f0f4ff'
  },
  checkboxContainer: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    marginBottom: 8
  },
  checkbox: {
    width: 18,
    height: 18,
    cursor: 'pointer'
  },
  modelName: {
    fontSize: 15,
    fontWeight: 'bold' as const,
    color: '#333'
  },
  modelDescription: {
    margin: 0,
    fontSize: 12,
    color: '#666',
    lineHeight: 1.4
  },
  buttonGroup: {
    display: 'flex',
    justifyContent: 'flex-end',
    marginTop: 24
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
  buttonDisabled: {
    background: '#e1e4e8',
    color: '#999',
    cursor: 'not-allowed'
  },
  placeholder: {
    display: 'flex',
    gap: 12,
    marginTop: 40,
    paddingTop: 32,
    borderTop: '1px solid #e1e4e8'
  },
  placeholderBox: {
    flex: 1,
    padding: 16,
    background: '#f6f8fa',
    borderRadius: 6,
    border: '2px dashed #d0d7de',
    textAlign: 'center' as const
  },
  placeholderActive: {
    background: '#e6f3ff',
    borderColor: '#667eea',
    borderStyle: 'solid' as const
  },
  placeholderText: {
    margin: 0,
    fontSize: 12,
    color: '#666'
  }
}

