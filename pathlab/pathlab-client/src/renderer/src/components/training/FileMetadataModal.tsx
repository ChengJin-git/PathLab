/**
 * FileMetadataModal Component
 *
 * Modal for setting metadata when uploading files.
 */

import React from 'react'
import { FileText } from 'lucide-react'
import { TaskType } from '../../constants/training'
import { FileMetadata } from '../../types/training'

export interface FileMetadataModalProps {
  taskType: TaskType
  selectedFiles: File[]
  fileMetadata: Map<string, FileMetadata>
  updateFileMetadata: (fileName: string, field: keyof FileMetadata, value: string) => void
  uploading: boolean
  onConfirm: () => void
  onCancel: () => void
}

export function FileMetadataModal({
  taskType,
  selectedFiles,
  fileMetadata,
  updateFileMetadata,
  uploading,
  onConfirm,
  onCancel,
}: FileMetadataModalProps) {
  const labelPlaceholder = taskType === 'survival_prediction' ? 'e.g., Surviving, Expired' : 'e.g., Benign, Malignant, Grade 1'
  const labelHint = taskType === 'survival_prediction' ? 'Label (Survival Outcome)' : 'Label (Disease Classification)'

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl max-w-4xl w-full max-h-[90vh] overflow-hidden flex flex-col">
        {/* Header */}
        <div className="p-6 border-b border-gray-200">
          <h3 className="text-2xl font-bold text-gray-900">Set Metadata for Files</h3>
          <p className="text-gray-600 mt-1">Add labels and case IDs for each file (optional)</p>
        </div>

        {/* File List */}
        <div className="flex-1 overflow-y-auto p-6">
          <div className="space-y-4">
            {selectedFiles.map((file, index) => (
              <div key={index} className="bg-gray-50 rounded-xl p-4 border border-gray-200">
                <div className="flex items-start gap-4">
                  {/* File Icon */}
                  <div className="flex-shrink-0 w-12 h-12 bg-blue-100 rounded-lg flex items-center justify-center">
                    <FileText className="w-6 h-6 text-blue-600" />
                  </div>

                  {/* File Info and Inputs */}
                  <div className="flex-1 min-w-0">
                    <p className="font-semibold text-gray-900 truncate mb-3">{file.name}</p>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">{labelHint}</label>
                        <input
                          type="text"
                          placeholder={labelPlaceholder}
                          value={fileMetadata.get(file.name)?.label || ''}
                          onChange={(e) => updateFileMetadata(file.name, 'label', e.target.value)}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">Case ID</label>
                        <input
                          type="text"
                          placeholder="e.g., case_001"
                          value={fileMetadata.get(file.name)?.case_id || ''}
                          onChange={(e) => updateFileMetadata(file.name, 'case_id', e.target.value)}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">Age</label>
                        <input
                          type="number"
                          placeholder="e.g., 45"
                          value={fileMetadata.get(file.name)?.age || ''}
                          onChange={(e) => updateFileMetadata(file.name, 'age', e.target.value)}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">Gender</label>
                        <select
                          value={fileMetadata.get(file.name)?.gender || ''}
                          onChange={(e) => updateFileMetadata(file.name, 'gender', e.target.value)}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
                        >
                          <option value="">Select Gender</option>
                          <option value="Male">Male</option>
                          <option value="Female">Female</option>
                          <option value="Unspecified">Unspecified</option>
                        </select>
                      </div>
                      <div className="col-span-2">
                        <label className="block text-sm font-medium text-gray-700 mb-1">Source (Organ/Tissue)</label>
                        <input
                          type="text"
                          placeholder="e.g., Cervix, Lung, Breast"
                          value={fileMetadata.get(file.name)?.source || ''}
                          onChange={(e) => updateFileMetadata(file.name, 'source', e.target.value)}
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
            <p className="text-sm text-gray-600">{selectedFiles.length} file(s) selected</p>
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
                Register All Files
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

