import React from 'react'

export type FileMetadataMap = Map<string, { label: string; case_id: string; age: string; gender: string; source: string }>

export interface FileMetadataModalProps {
  selectedFiles: File[]
  fileMetadata: FileMetadataMap
  onUpdateMetadata: (fileName: string, field: 'label' | 'case_id' | 'age' | 'gender' | 'source', value: string) => void
  onCancel: () => void
  onConfirm: () => void
  uploading: boolean
}

export function FileMetadataModal({ selectedFiles, fileMetadata, onUpdateMetadata, onCancel, onConfirm, uploading }: FileMetadataModalProps) {
  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl max-w-4xl w-full max-h-[90vh] overflow-hidden flex flex-col">
        {/* Header */}
        <div className="p-6 border-b border-gray-200">
          <h3 className="text-2xl font-bold text-gray-900">Set Metadata for Files</h3>
          <p className="text-gray-600 mt-1">Add metadata for each file (all fields are optional)</p>
        </div>

        {/* File List */}
        <div className="flex-1 overflow-y-auto p-6">
          <div className="space-y-4">
            {selectedFiles.map((file, index) => (
              <div key={index} className="bg-gray-50 rounded-xl p-4 border border-gray-200">
                <div className="flex items-start gap-4">
                  {/* File Icon and Name */}
                  <div className="flex-shrink-0 w-12 h-12 bg-blue-100 rounded-lg flex items-center justify-center">
                    <svg className="w-6 h-6 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    </svg>
                  </div>

                  {/* File Info and Inputs */}
                  <div className="flex-1 min-w-0">
                    <p className="font-semibold text-gray-900 truncate mb-3">{file.name}</p>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                          Label (Disease Classification)
                        </label>
                        <input
                          type="text"
                          placeholder="e.g., Benign, Malignant, Grade 1"
                          value={fileMetadata.get(file.name)?.label || ''}
                          onChange={(e) => onUpdateMetadata(file.name, 'label', e.target.value)}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                          Case ID
                        </label>
                        <input
                          type="text"
                          placeholder="e.g., case_001"
                          value={fileMetadata.get(file.name)?.case_id || ''}
                          onChange={(e) => onUpdateMetadata(file.name, 'case_id', e.target.value)}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                          Age
                        </label>
                        <input
                          type="number"
                          placeholder="e.g., 45"
                          value={fileMetadata.get(file.name)?.age || ''}
                          onChange={(e) => onUpdateMetadata(file.name, 'age', e.target.value)}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                          Gender
                        </label>
                        <select
                          value={fileMetadata.get(file.name)?.gender || ''}
                          onChange={(e) => onUpdateMetadata(file.name, 'gender', e.target.value)}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
                        >
                          <option value="">Select Gender</option>
                          <option value="Male">Male</option>
                          <option value="Female">Female</option>
                          <option value="Unspecified">Unspecified</option>
                        </select>
                      </div>
                      <div className="col-span-2">
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                          Source (Organ/Tissue)
                        </label>
                        <input
                          type="text"
                          placeholder="e.g., Cervix, Lung, Breast"
                          value={fileMetadata.get(file.name)?.source || ''}
                          onChange={(e) => onUpdateMetadata(file.name, 'source', e.target.value)}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
                        />
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Footer */}
        <div className="p-6 border-t border-gray-200 bg-gray-50">
          <div className="flex justify-between items-center">
            <p className="text-sm text-gray-600">
              {selectedFiles.length} file(s) selected
            </p>
            <div className="flex gap-3">
              <button
                onClick={onCancel}
                className="px-6 py-2.5 text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors font-medium"
              >
                Cancel
              </button>
              <button
                onClick={onConfirm}
                disabled={uploading}
                className="px-6 py-2.5 bg-gradient-to-r from-blue-600 to-blue-700 text-white rounded-lg hover:from-blue-700 hover:to-blue-800 transition-all font-semibold shadow-lg shadow-blue-200 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Upload All Files
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

