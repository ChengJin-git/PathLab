import React, { useState, useEffect, useRef, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchWSIList, uploadWSIFile, uploadWSIByPath } from '../api'

// Available models
const AVAILABLE_MODELS = [
  { id: 'resnet50', name: 'ResNet50', description: 'General-purpose image analysis model' },
  { id: 'vit_base', name: 'ViT-Base', description: 'Advanced vision analysis model' },
  { id: 'ctranspath', name: 'CTransPath', description: 'Specialized for pathology images' },
  { id: 'uni', name: 'UNI', description: 'Universal pathology model (recommended)' },
]

export default function NewTaskPage() {
  const navigate = useNavigate()
  const [currentStep, setCurrentStep] = useState(1)
  
  // Step 1: Task Description
  const [taskDescription, setTaskDescription] = useState('')
  const [selectedModels, setSelectedModels] = useState<string[]>(['resnet50'])
  
  // Step 2: Data Selection
  const [items, setItems] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState<string>('')
  const fileInputRef = useRef<HTMLInputElement>(null)
  
  // Step 3: Training
  const [trainingStatus, setTrainingStatus] = useState<'idle' | 'preparing' | 'training' | 'completed'>('idle')
  const [trainingProgress, setTrainingProgress] = useState(0)
  const [trainingLogs, setTrainingLogs] = useState<string[]>([])

  useEffect(() => {
    if (currentStep === 2) {
      loadWSIList()
    }
  }, [currentStep])

  const loadWSIList = async () => {
    setLoading(true)
    try {
      const data = await fetchWSIList()
      setItems(data.items || [])
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  const handleModelToggle = (modelId: string) => {
    setSelectedModels(prev =>
      prev.includes(modelId)
        ? prev.filter(id => id !== modelId)
        : [...prev, modelId]
    )
  }

  const toggleSelection = (wsi_id: string) => {
    const newSelected = new Set(selectedIds)
    if (newSelected.has(wsi_id)) {
      newSelected.delete(wsi_id)
    } else {
      newSelected.add(wsi_id)
    }
    setSelectedIds(newSelected)
  }

  const handleFileUpload = async (files: FileList | null) => {
    if (!files || files.length === 0) return
    setUploading(true)
    setUploadProgress(`Uploading ${files.length} file(s)...`)

    try {
      let successCount = 0
      for (let i = 0; i < files.length; i++) {
        const file = files[i]
        setUploadProgress(`Uploading ${i + 1}/${files.length}: ${file.name}`)
        try {
          await uploadWSIFile(file)
          successCount++
        } catch (err) {
          console.error(`Failed to upload ${file.name}:`, err)
        }
      }
      setUploadProgress(`Upload complete! Success: ${successCount}`)
      await loadWSIList()
      setTimeout(() => setUploadProgress(''), 3000)
    } catch (err) {
      console.error(err)
    } finally {
      setUploading(false)
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    }
  }

  const startTraining = async () => {
    setTrainingStatus('preparing')
    setTrainingProgress(0)
    setTrainingLogs([])
    
    const addLog = (msg: string) => {
      const timestamp = new Date().toLocaleTimeString()
      setTrainingLogs(prev => [...prev, `[${timestamp}] ${msg}`])
    }
    
    const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))
    
    addLog('Preparing training environment...')
    await sleep(1000)
    
    setTrainingStatus('training')
    addLog('Loading WSI data...')
    await sleep(800)
    
    addLog(`Training on ${selectedIds.size} WSI files...`)
    
    for (let i = 0; i <= 100; i += 5) {
      setTrainingProgress(i)
      if (i % 20 === 0) {
        addLog(`Training progress: ${i}%`)
      }
      await sleep(300)
    }
    
    addLog('Training completed successfully!')
    setTrainingStatus('completed')
    
    // Save to sessionStorage
    sessionStorage.setItem('taskDescription', taskDescription)
    sessionStorage.setItem('selectedModels', JSON.stringify(selectedModels))
    sessionStorage.setItem('selectedTrainingWSIs', JSON.stringify(Array.from(selectedIds)))
    sessionStorage.setItem('trainingCompleted', 'true')
  }

  const canProceedStep1 = useMemo(() => {
    return taskDescription.trim().length > 0 && selectedModels.length > 0
  }, [taskDescription, selectedModels])

  const canProceedStep2 = useMemo(() => {
    return selectedIds.size > 0
  }, [selectedIds])

  const canProceedStep3 = useMemo(() => {
    return trainingStatus === 'completed'
  }, [trainingStatus])

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-gray-900">New Analysis Task</h1>
        <p className="text-gray-600 mt-1">Create and train a new analysis model</p>
      </div>

      {/* Progress Steps */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <div className={`w-8 h-8 rounded-full flex items-center justify-center font-semibold text-sm ${
              currentStep >= 1 ? 'bg-primary-600 text-white' : 'bg-gray-200 text-gray-500'
            }`}>
              {currentStep > 1 ? '✓' : '1'}
            </div>
            <span className={`font-medium text-sm ${currentStep >= 1 ? 'text-gray-900' : 'text-gray-500'}`}>
              Setup
            </span>
          </div>
          <div className={`flex-1 h-1 mx-4 ${currentStep > 1 ? 'bg-primary-600' : 'bg-gray-200'}`}></div>

          <div className="flex items-center space-x-2">
            <div className={`w-8 h-8 rounded-full flex items-center justify-center font-semibold text-sm ${
              currentStep >= 2 ? 'bg-primary-600 text-white' : 'bg-gray-200 text-gray-500'
            }`}>
              {currentStep > 2 ? '✓' : '2'}
            </div>
            <span className={`font-medium text-sm ${currentStep >= 2 ? 'text-gray-900' : 'text-gray-500'}`}>
              Select Slides
            </span>
          </div>
          <div className={`flex-1 h-1 mx-4 ${currentStep > 2 ? 'bg-primary-600' : 'bg-gray-200'}`}></div>

          <div className="flex items-center space-x-2">
            <div className={`w-8 h-8 rounded-full flex items-center justify-center font-semibold text-sm ${
              currentStep >= 3 ? 'bg-primary-600 text-white' : 'bg-gray-200 text-gray-500'
            }`}>
              {currentStep > 3 ? '✓' : '3'}
            </div>
            <span className={`font-medium text-sm ${currentStep >= 3 ? 'text-gray-900' : 'text-gray-500'}`}>
              Train
            </span>
          </div>
        </div>
      </div>

      {/* Step 1: Task Description */}
      {currentStep === 1 && (
        <>
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Analysis Goal
            </label>
            <textarea
              className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent transition-all"
              value={taskDescription}
              onChange={(e) => setTaskDescription(e.target.value)}
              placeholder="e.g., Classify lung cancer pathology slides into LUAD, LUSC, and Normal tissue..."
              rows={6}
            />
          </div>

          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Select AI Models
            </label>
            <p className="text-sm text-gray-500 mb-4">Choose one or more models for analysis</p>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {AVAILABLE_MODELS.map((model) => (
                <div
                  key={model.id}
                  onClick={() => handleModelToggle(model.id)}
                  className={`p-4 border-2 rounded-lg cursor-pointer transition-all ${
                    selectedModels.includes(model.id)
                      ? 'border-primary-500 bg-primary-50'
                      : 'border-gray-200 hover:border-gray-300'
                  }`}
                >
                  <div className="flex items-start space-x-3">
                    <input
                      type="checkbox"
                      checked={selectedModels.includes(model.id)}
                      onChange={() => {}}
                      className="mt-1 h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded"
                    />
                    <div className="flex-1">
                      <div className="font-semibold text-gray-900">{model.name}</div>
                      <div className="text-sm text-gray-600 mt-1">{model.description}</div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="flex justify-between items-center">
            <button
              onClick={() => navigate('/')}
              className="px-6 py-2.5 border border-gray-300 text-gray-700 font-medium rounded-lg hover:bg-gray-50 transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={() => setCurrentStep(2)}
              disabled={!canProceedStep1}
              className={`px-6 py-2.5 font-medium rounded-lg transition-all ${
                canProceedStep1
                  ? 'bg-blue-600 text-white hover:bg-blue-700 shadow-md'
                  : 'bg-gray-200 text-gray-400 cursor-not-allowed opacity-60'
              }`}
            >
              Next: Select Data →
            </button>
          </div>
        </>
      )}

      {/* Step 2: Data Selection */}
      {currentStep === 2 && (
        <>
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-lg font-semibold text-gray-900">Select Training Data</h3>
                <p className="text-sm text-gray-600 mt-1">
                  Selected {selectedIds.size} WSI file(s) for training
                </p>
              </div>
              <div className="flex space-x-2">
                <button
                  onClick={() => fileInputRef.current?.click()}
                  disabled={uploading}
                  className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition-colors text-sm font-medium disabled:opacity-50"
                >
                  📁 Upload Files
                </button>
              </div>
            </div>

            {uploadProgress && (
              <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-lg text-sm text-blue-800">
                {uploadProgress}
              </div>
            )}

            <input
              ref={fileInputRef}
              type="file"
              accept=".svs,.svslide,.ndpi,.scn,.mrxs,.bif,.tif,.tiff"
              multiple
              style={{ display: 'none' }}
              onChange={(e) => handleFileUpload(e.target.files)}
            />

            {loading ? (
              <div className="flex justify-center py-8">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
              </div>
            ) : items.length === 0 ? (
              <div className="text-center py-8 text-gray-500">
                No WSI files available. Please upload some files first.
              </div>
            ) : (
              <div className="border border-gray-200 rounded-lg overflow-hidden">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
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
                          className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded"
                        />
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">WSI ID</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Label</th>
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {items.map((it) => (
                      <tr key={it.wsi_id} className="hover:bg-gray-50">
                        <td className="px-4 py-3">
                          <input
                            type="checkbox"
                            checked={selectedIds.has(it.wsi_id)}
                            onChange={() => toggleSelection(it.wsi_id)}
                            className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded"
                          />
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-900">{it.wsi_id}</td>
                        <td className="px-4 py-3 text-sm text-gray-600">{it.label || '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="flex justify-between">
            <button
              onClick={() => setCurrentStep(1)}
              className="px-6 py-2.5 border border-gray-300 text-gray-700 font-medium rounded-lg hover:bg-gray-50 transition-colors"
            >
              ← Back
            </button>
            <button
              onClick={() => setCurrentStep(3)}
              disabled={!canProceedStep2}
              className={`px-6 py-2.5 font-medium rounded-lg transition-colors ${
                canProceedStep2
                  ? 'bg-primary-600 text-white hover:bg-primary-700'
                  : 'bg-gray-300 text-gray-500 cursor-not-allowed'
              }`}
            >
              Next: Train Model →
            </button>
          </div>
        </>
      )}

      {/* Step 3: Training */}
      {currentStep === 3 && (
        <>
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">Model Training</h3>

            <div className="mb-6">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-medium text-gray-700">Progress</span>
                <span className="text-sm font-medium text-gray-900">{trainingProgress}%</span>
              </div>
              <div className="w-full bg-gray-200 rounded-full h-3">
                <div
                  className="bg-primary-600 h-3 rounded-full transition-all duration-300"
                  style={{ width: `${trainingProgress}%` }}
                />
              </div>
            </div>

            <div className="mb-6">
              <div className="flex items-center space-x-2 mb-2">
                <span className="text-sm font-medium text-gray-700">Status:</span>
                <span className={`px-3 py-1 rounded-full text-xs font-medium ${
                  trainingStatus === 'idle' ? 'bg-gray-100 text-gray-800' :
                  trainingStatus === 'preparing' ? 'bg-yellow-100 text-yellow-800' :
                  trainingStatus === 'training' ? 'bg-blue-100 text-blue-800' :
                  'bg-green-100 text-green-800'
                }`}>
                  {trainingStatus === 'idle' ? 'Ready' :
                   trainingStatus === 'preparing' ? 'Preparing' :
                   trainingStatus === 'training' ? 'Training' :
                   'Completed'}
                </span>
              </div>
            </div>

            <div className="bg-gray-900 rounded-lg p-4 h-64 overflow-y-auto font-mono text-xs text-green-400">
              {trainingLogs.length === 0 ? (
                <div className="text-gray-500">Waiting to start training...</div>
              ) : (
                trainingLogs.map((log, idx) => (
                  <div key={idx}>{log}</div>
                ))
              )}
            </div>
          </div>

          <div className="flex justify-between">
            <button
              onClick={() => setCurrentStep(2)}
              disabled={trainingStatus !== 'idle'}
              className="px-6 py-2.5 border border-gray-300 text-gray-700 font-medium rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50"
            >
              ← Back
            </button>
            <div className="flex space-x-3">
              {trainingStatus === 'idle' && (
                <button
                  onClick={startTraining}
                  className="px-6 py-2.5 bg-primary-600 text-white font-medium rounded-lg hover:bg-primary-700 transition-colors"
                >
                  Start Training
                </button>
              )}
              {trainingStatus === 'completed' && (
                <button
                  onClick={() => navigate('/wsi-list')}
                  className="px-6 py-2.5 bg-green-600 text-white font-medium rounded-lg hover:bg-green-700 transition-colors"
                >
                  View Results in WSI Browser →
                </button>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}

