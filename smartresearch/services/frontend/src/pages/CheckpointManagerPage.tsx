import { useState, useEffect } from 'react'

interface Checkpoint {
  id: string
  name: string
  model_type: string
  feature_dim: number
  num_classes: number
  accuracy?: number
  epoch?: number
  created_at: string
  file_size: string
  status: 'active' | 'inactive'
  description?: string
}

export default function CheckpointManagerPage() {
  const [checkpoints, setCheckpoints] = useState<Checkpoint[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedCheckpoint, setSelectedCheckpoint] = useState<string | null>(null)
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [checkpointToDelete, setCheckpointToDelete] = useState<Checkpoint | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid')

  // Mock data - replace with actual API call
  useEffect(() => {
    loadCheckpoints()
  }, [])

  const loadCheckpoints = async () => {
    setLoading(true)
    try {
      // TODO: Replace with actual API call
      // const data = await fetchCheckpoints()
      
      // Mock data for demonstration
      const mockCheckpoints: Checkpoint[] = [
        {
          id: 'ckpt_001',
          name: 'lung_cancer_3class.pth',
          model_type: 'ABMIL',
          feature_dim: 2048,
          num_classes: 3,
          accuracy: 0.95,
          epoch: 100,
          created_at: '2024-10-15',
          file_size: '45.2 MB',
          status: 'active',
          description: 'Lung cancer classification (LUAD, LUSC, Normal)'
        },
        {
          id: 'ckpt_002',
          name: 'breast_cancer_2class.pth',
          model_type: 'ABMIL',
          feature_dim: 2048,
          num_classes: 2,
          accuracy: 0.92,
          epoch: 80,
          created_at: '2024-10-10',
          file_size: '42.8 MB',
          status: 'inactive',
          description: 'Breast cancer binary classification'
        },
        {
          id: 'ckpt_003',
          name: 'baseline_mean.pth',
          model_type: 'Mean Pooling',
          feature_dim: 1024,
          num_classes: 3,
          accuracy: 0.78,
          epoch: 50,
          created_at: '2024-10-05',
          file_size: '12.5 MB',
          status: 'inactive',
          description: 'Baseline model with mean pooling aggregation'
        },
        {
          id: 'ckpt_004',
          name: 'resnet50_pretrained.pth',
          model_type: 'ResNet50',
          feature_dim: 2048,
          num_classes: 5,
          accuracy: 0.88,
          epoch: 120,
          created_at: '2024-09-28',
          file_size: '98.3 MB',
          status: 'inactive',
          description: 'Multi-class tissue classification'
        }
      ]
      
      setCheckpoints(mockCheckpoints)
    } catch (error) {
      console.error('Failed to load checkpoints:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleActivate = (checkpointId: string) => {
    setCheckpoints(prev => prev.map(ckpt => ({
      ...ckpt,
      status: ckpt.id === checkpointId ? 'active' : 'inactive'
    })))
    setSelectedCheckpoint(checkpointId)
  }

  const handleDelete = (checkpoint: Checkpoint) => {
    setCheckpointToDelete(checkpoint)
    setShowDeleteModal(true)
  }

  const confirmDelete = async () => {
    if (!checkpointToDelete) return
    
    setDeleting(true)
    try {
      // TODO: Replace with actual API call
      // await deleteCheckpoint(checkpointToDelete.id)
      
      setCheckpoints(prev => prev.filter(ckpt => ckpt.id !== checkpointToDelete.id))
      setShowDeleteModal(false)
      setCheckpointToDelete(null)
    } catch (error) {
      console.error('Failed to delete checkpoint:', error)
    } finally {
      setDeleting(false)
    }
  }

  const getModelTypeColor = (type: string) => {
    const colors: Record<string, string> = {
      'ABMIL': 'bg-purple-100 text-purple-700',
      'Mean Pooling': 'bg-blue-100 text-blue-700',
      'ResNet50': 'bg-green-100 text-green-700',
      'ViT': 'bg-pink-100 text-pink-700'
    }
    return colors[type] || 'bg-gray-100 text-gray-700'
  }

  if (loading) {
    return (
      <div className="max-w-7xl mx-auto">
        <div className="flex items-center justify-center h-64">
          <div className="text-center">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
            <p className="text-gray-600">Loading checkpoints...</p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-7xl mx-auto">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 flex items-center">
          <span className="text-4xl mr-3">💾</span>
          Checkpoint Manager
        </h1>
        <p className="text-gray-600 mt-2">Manage and organize your trained model checkpoints</p>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-gray-600">Total Checkpoints</p>
              <p className="text-2xl font-bold text-gray-900">{checkpoints.length}</p>
            </div>
            <div className="text-3xl">📦</div>
          </div>
        </div>
        
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-gray-600">Active Model</p>
              <p className="text-2xl font-bold text-green-600">
                {checkpoints.filter(c => c.status === 'active').length}
              </p>
            </div>
            <div className="text-3xl">✅</div>
          </div>
        </div>
        
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-gray-600">Total Size</p>
              <p className="text-2xl font-bold text-gray-900">
                {checkpoints.reduce((sum, c) => sum + parseFloat(c.file_size), 0).toFixed(1)} MB
              </p>
            </div>
            <div className="text-3xl">💿</div>
          </div>
        </div>
        
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-gray-600">Best Accuracy</p>
              <p className="text-2xl font-bold text-blue-600">
                {Math.max(...checkpoints.map(c => c.accuracy || 0)).toFixed(2)}
              </p>
            </div>
            <div className="text-3xl">🎯</div>
          </div>
        </div>
      </div>

      {/* Toolbar */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mb-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-4">
            <button className="px-4 py-2 bg-gradient-to-r from-blue-600 to-blue-700 text-white text-sm font-medium rounded-lg hover:from-blue-700 hover:to-blue-800 transition-all shadow-sm">
              <span className="mr-2">⬆️</span>
              Upload Checkpoint
            </button>
            <button className="px-4 py-2 bg-white border border-gray-300 text-gray-700 text-sm font-medium rounded-lg hover:bg-gray-50 transition-all">
              <span className="mr-2">🔄</span>
              Refresh
            </button>
          </div>
          
          <div className="flex items-center space-x-2">
            <button
              onClick={() => setViewMode('grid')}
              className={`p-2 rounded-lg transition-colors ${
                viewMode === 'grid' ? 'bg-blue-100 text-blue-600' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                <path d="M5 3a2 2 0 00-2 2v2a2 2 0 002 2h2a2 2 0 002-2V5a2 2 0 00-2-2H5zM5 11a2 2 0 00-2 2v2a2 2 0 002 2h2a2 2 0 002-2v-2a2 2 0 00-2-2H5zM11 5a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V5zM11 13a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" />
              </svg>
            </button>
            <button
              onClick={() => setViewMode('list')}
              className={`p-2 rounded-lg transition-colors ${
                viewMode === 'list' ? 'bg-blue-100 text-blue-600' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M3 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1z" clipRule="evenodd" />
              </svg>
            </button>
          </div>
        </div>
      </div>

      {/* Checkpoints Display */}
      {checkpoints.length === 0 ? (
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-12 text-center">
          <div className="text-6xl mb-4">📦</div>
          <h3 className="text-xl font-semibold text-gray-900 mb-2">No Checkpoints Found</h3>
          <p className="text-gray-600 mb-6">Upload your first model checkpoint to get started</p>
          <button className="px-6 py-3 bg-gradient-to-r from-blue-600 to-blue-700 text-white font-medium rounded-lg hover:from-blue-700 hover:to-blue-800 transition-all shadow-sm">
            Upload Checkpoint
          </button>
        </div>
      ) : viewMode === 'grid' ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {checkpoints.map((checkpoint) => (
            <div
              key={checkpoint.id}
              className={`bg-white rounded-lg shadow-sm border-2 transition-all hover:shadow-md ${
                checkpoint.status === 'active' ? 'border-green-500' : 'border-gray-200'
              }`}
            >
              <div className="p-6">
                {/* Header */}
                <div className="flex items-start justify-between mb-4">
                  <div className="flex-1">
                    <h3 className="text-lg font-semibold text-gray-900 mb-1 truncate">
                      {checkpoint.name}
                    </h3>
                    <span className={`inline-block px-2 py-1 text-xs font-medium rounded ${getModelTypeColor(checkpoint.model_type)}`}>
                      {checkpoint.model_type}
                    </span>
                  </div>
                  {checkpoint.status === 'active' && (
                    <span className="ml-2 px-2 py-1 bg-green-100 text-green-700 text-xs font-medium rounded">
                      Active
                    </span>
                  )}
                </div>

                {/* Description */}
                {checkpoint.description && (
                  <p className="text-sm text-gray-600 mb-4 line-clamp-2">
                    {checkpoint.description}
                  </p>
                )}

                {/* Metrics */}
                <div className="space-y-2 mb-4">
                  <div className="flex justify-between text-sm">
                    <span className="text-gray-600">Accuracy</span>
                    <span className="font-medium text-gray-900">
                      {checkpoint.accuracy ? `${(checkpoint.accuracy * 100).toFixed(1)}%` : 'N/A'}
                    </span>
                  </div>
                  <div className="flex justify-between text-sm">
                    <span className="text-gray-600">Classes</span>
                    <span className="font-medium text-gray-900">{checkpoint.num_classes}</span>
                  </div>
                  <div className="flex justify-between text-sm">
                    <span className="text-gray-600">Feature Dim</span>
                    <span className="font-medium text-gray-900">{checkpoint.feature_dim}</span>
                  </div>
                  <div className="flex justify-between text-sm">
                    <span className="text-gray-600">Epochs</span>
                    <span className="font-medium text-gray-900">{checkpoint.epoch || 'N/A'}</span>
                  </div>
                </div>

                {/* Footer */}
                <div className="pt-4 border-t border-gray-200">
                  <div className="flex items-center justify-between text-xs text-gray-500 mb-3">
                    <span>{checkpoint.created_at}</span>
                    <span>{checkpoint.file_size}</span>
                  </div>

                  <div className="flex space-x-2">
                    {checkpoint.status === 'inactive' ? (
                      <button
                        onClick={() => handleActivate(checkpoint.id)}
                        className="flex-1 px-3 py-2 bg-gradient-to-r from-green-600 to-green-700 text-white text-sm font-medium rounded-lg hover:from-green-700 hover:to-green-800 transition-all"
                      >
                        Activate
                      </button>
                    ) : (
                      <button
                        disabled
                        className="flex-1 px-3 py-2 bg-gray-100 text-gray-400 text-sm font-medium rounded-lg cursor-not-allowed"
                      >
                        Active
                      </button>
                    )}
                    <button
                      onClick={() => handleDelete(checkpoint)}
                      className="px-3 py-2 bg-white border border-red-300 text-red-600 text-sm font-medium rounded-lg hover:bg-red-50 transition-all"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        /* List View */
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Checkpoint
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Model Type
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Accuracy
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Classes
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Size
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Status
                </th>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {checkpoints.map((checkpoint) => (
                <tr key={checkpoint.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div>
                      <div className="text-sm font-medium text-gray-900">{checkpoint.name}</div>
                      <div className="text-xs text-gray-500">{checkpoint.created_at}</div>
                    </div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <span className={`inline-block px-2 py-1 text-xs font-medium rounded ${getModelTypeColor(checkpoint.model_type)}`}>
                      {checkpoint.model_type}
                    </span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                    {checkpoint.accuracy ? `${(checkpoint.accuracy * 100).toFixed(1)}%` : 'N/A'}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                    {checkpoint.num_classes}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                    {checkpoint.file_size}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    {checkpoint.status === 'active' ? (
                      <span className="px-2 py-1 bg-green-100 text-green-700 text-xs font-medium rounded">
                        Active
                      </span>
                    ) : (
                      <span className="px-2 py-1 bg-gray-100 text-gray-600 text-xs font-medium rounded">
                        Inactive
                      </span>
                    )}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                    <div className="flex justify-end space-x-2">
                      {checkpoint.status === 'inactive' ? (
                        <button
                          onClick={() => handleActivate(checkpoint.id)}
                          className="text-green-600 hover:text-green-900"
                        >
                          Activate
                        </button>
                      ) : (
                        <span className="text-gray-400">Active</span>
                      )}
                      <button
                        onClick={() => handleDelete(checkpoint)}
                        className="text-red-600 hover:text-red-900"
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {showDeleteModal && checkpointToDelete && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 max-w-md w-full mx-4">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">Delete Checkpoint</h3>
            <p className="text-gray-600 mb-6">
              Are you sure you want to delete <strong>{checkpointToDelete.name}</strong>? This action cannot be undone.
            </p>
            <div className="flex justify-end space-x-3">
              <button
                onClick={() => setShowDeleteModal(false)}
                disabled={deleting}
                className="px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={confirmDelete}
                disabled={deleting}
                className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors disabled:opacity-50"
              >
                {deleting ? 'Deleting...' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

