import React from 'react'
import { useTranslation } from 'react-i18next'

export type FileMetadataMap = Map<string, { label: string; case_id: string; age: string; gender: string; source: string }>

export interface FileMetadataModalProps {
  selectedFiles: File[]
  fileMetadata: FileMetadataMap
  datasetType?: 'classification' | 'survival' | 'segmentation'
  onUpdateMetadata: (fileName: string, field: 'label' | 'case_id' | 'age' | 'gender' | 'source', value: string) => void
  onCancel: () => void
  onConfirm: () => void
  uploading: boolean
}

export function FileMetadataModal({ selectedFiles, fileMetadata, datasetType = 'classification', onUpdateMetadata, onCancel, onConfirm, uploading }: FileMetadataModalProps) {
  const { t } = useTranslation()
  const showLabelField = datasetType !== 'segmentation'
  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl max-w-4xl w-full max-h-[90vh] overflow-hidden flex flex-col">
        <div className="p-6 border-b border-gray-200">
          <h3 className="text-2xl font-bold text-gray-900">{t('listComponents.fileMetadata.setMetadataForFiles')}</h3>
          <p className="text-gray-600 mt-1">{t('listComponents.fileMetadata.addMetadataDescription')}</p>
        </div>

        <div className="flex-1 overflow-y-auto p-6">
          <div className="space-y-4">
            {selectedFiles.map((file, index) => (
              <div key={index} className="bg-gray-50 rounded-xl p-4 border border-gray-200">
                <div className="flex items-start gap-4">
                  <div className="flex-shrink-0 w-12 h-12 bg-blue-100 rounded-lg flex items-center justify-center">
                    <svg className="w-6 h-6 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    </svg>
                  </div>

                  <div className="flex-1 min-w-0">
                    <p className="font-semibold text-gray-900 truncate mb-3">{file.name}</p>
                    <div className="grid grid-cols-2 gap-3">
                      {showLabelField && (
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-1">
                            {t('listComponents.fileMetadata.labelDiseaseClassification')}
                          </label>
                          <input
                            type="text"
                            placeholder={t('listComponents.fileMetadata.labelPlaceholder')}
                            value={fileMetadata.get(file.name)?.label || ''}
                            onChange={(e) => onUpdateMetadata(file.name, 'label', e.target.value)}
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
                          />
                        </div>
                      )}
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                          {t('listComponents.fileMetadata.caseId')}
                        </label>
                        <input
                          type="text"
                          placeholder={t('listComponents.fileMetadata.caseIdPlaceholder')}
                          value={fileMetadata.get(file.name)?.case_id || ''}
                          onChange={(e) => onUpdateMetadata(file.name, 'case_id', e.target.value)}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                          {t('listComponents.fileMetadata.age')}
                        </label>
                        <input
                          type="number"
                          placeholder={t('listComponents.fileMetadata.agePlaceholder')}
                          value={fileMetadata.get(file.name)?.age || ''}
                          onChange={(e) => onUpdateMetadata(file.name, 'age', e.target.value)}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                          {t('listComponents.fileMetadata.gender')}
                        </label>
                        <select
                          value={fileMetadata.get(file.name)?.gender || ''}
                          onChange={(e) => onUpdateMetadata(file.name, 'gender', e.target.value)}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-sm"
                        >
                          <option value="">{t('listComponents.fileMetadata.selectGender')}</option>
                          <option value="Male">{t('listComponents.fileMetadata.male')}</option>
                          <option value="Female">{t('listComponents.fileMetadata.female')}</option>
                          <option value="Unspecified">{t('listComponents.fileMetadata.unspecified')}</option>
                        </select>
                      </div>
                      <div className="col-span-2">
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                          {t('listComponents.fileMetadata.sourceOrganTissue')}
                        </label>
                        <input
                          type="text"
                          placeholder={t('listComponents.fileMetadata.sourcePlaceholder')}
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

        <div className="p-6 border-t border-gray-200 bg-gray-50">
          <div className="flex justify-between items-center">
            <p className="text-sm text-gray-600">
              {t('listComponents.fileMetadata.filesSelected', { count: selectedFiles.length })}
            </p>
            <div className="flex gap-3">
              <button
                onClick={onCancel}
                className="px-6 py-2.5 text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors font-medium"
              >
                {t('listComponents.fileMetadata.cancel')}
              </button>
              <button
                onClick={onConfirm}
                disabled={uploading}
                className="px-6 py-2.5 bg-gradient-to-r from-blue-600 to-blue-700 text-white rounded-lg hover:from-blue-700 hover:to-blue-800 transition-all font-semibold shadow-lg shadow-blue-200 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {t('listComponents.fileMetadata.uploadAllFiles')}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
