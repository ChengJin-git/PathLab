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
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-gray-900">Task Setup</h1>
        <p className="text-gray-600 mt-1">Describe your research task and select models</p>
      </div>

      {/* Progress Steps */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <div className="w-8 h-8 rounded-full bg-primary-600 text-white flex items-center justify-center font-semibold text-sm">
              1
            </div>
            <span className="font-medium text-gray-900 text-sm">Task Setup</span>
          </div>
          <div className="flex-1 h-1 bg-gray-200 mx-4"></div>
          <div className="flex items-center space-x-2">
            <div className="w-8 h-8 rounded-full bg-gray-200 text-gray-500 flex items-center justify-center font-semibold text-sm">
              2
            </div>
            <span className="text-gray-500 text-sm">Select Data</span>
          </div>
          <div className="flex-1 h-1 bg-gray-200 mx-4"></div>
          <div className="flex items-center space-x-2">
            <div className="w-8 h-8 rounded-full bg-gray-200 text-gray-500 flex items-center justify-center font-semibold text-sm">
              3
            </div>
            <span className="text-gray-500 text-sm">Training</span>
          </div>
          <div className="flex-1 h-1 bg-gray-200 mx-4"></div>
          <div className="flex items-center space-x-2">
            <div className="w-8 h-8 rounded-full bg-gray-200 text-gray-500 flex items-center justify-center font-semibold text-sm">
              4
            </div>
            <span className="text-gray-500 text-sm">Inference</span>
          </div>
        </div>
      </div>

      {/* Task Description */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Task Description
        </label>
        <textarea
          className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent transition-all"
          value={taskDescription}
          onChange={(e) => setTaskDescription(e.target.value)}
          placeholder="e.g., Classify lung cancer pathology slides into LUAD, LUSC, and Normal tissue..."
          rows={6}
        />
      </div>

      {/* Model Selection */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Select Feature Extraction Models
        </label>
        <p className="text-sm text-gray-500 mb-4">Choose one or more models for feature extraction</p>

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

      {/* Action Buttons */}
      <div className="flex items-center justify-between">
        <button
          onClick={() => navigate('/')}
          className="px-6 py-2.5 border border-gray-300 text-gray-700 font-medium rounded-lg hover:bg-gray-50 transition-colors"
        >
          Cancel
        </button>
        <button
          onClick={handleNext}
          disabled={!taskDescription.trim() || selectedModels.length === 0}
          className={`px-6 py-2.5 font-medium rounded-lg transition-colors ${
            taskDescription.trim() && selectedModels.length > 0
              ? 'bg-primary-600 text-white hover:bg-primary-700'
              : 'bg-gray-300 text-gray-500 cursor-not-allowed'
          }`}
        >
          Next: Select Training Data →
        </button>
      </div>
    </div>
  )
}

