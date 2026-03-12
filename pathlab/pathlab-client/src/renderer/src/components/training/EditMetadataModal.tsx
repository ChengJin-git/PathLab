/**
 * EditMetadataModal Component
 *
 * Modal for editing metadata of a single slide.
 */

import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Edit2 } from 'lucide-react'
import { TaskType } from '../../constants/training'

export interface WSIEditInfo {
  wsi_id: string
  label?: string
  case_id?: string
  age?: number
  gender?: string
  event_time?: number
  event_status?: number
}

export interface EditMetadataModalProps {
  taskType: TaskType
  editingWSI: WSIEditInfo
  updating: boolean
  onConfirm: (data: {
    label: string
    case_id: string
    age: string
    gender: string
    event_time: string
    event_status: string
  }) => void
  onCancel: () => void
}

export function EditMetadataModal({ taskType, editingWSI, updating, onConfirm, onCancel }: EditMetadataModalProps) {
  const { t } = useTranslation()
  const [label, setLabel] = useState('')
  const [caseId, setCaseId] = useState('')
  const [age, setAge] = useState('')
  const [gender, setGender] = useState('')
  const [eventTime, setEventTime] = useState('')
  const [eventStatus, setEventStatus] = useState('')

  useEffect(() => {
    setLabel(editingWSI.label || '')
    setCaseId(editingWSI.case_id || '')
    setAge(editingWSI.age?.toString() || '')
    setGender(editingWSI.gender || '')
    setEventTime(editingWSI.event_time?.toString() || '')
    setEventStatus(editingWSI.event_status?.toString() || '')
  }, [editingWSI])

  const handleSubmit = () => {
    onConfirm({ label, case_id: caseId, age, gender, event_time: eventTime, event_status: eventStatus })
  }

  const isSurvival = taskType === 'survival'
  const isSegmentation = taskType === 'segmentation'
  const labelHint = t('training.editMetadata.labelHint')

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full p-6">
        {/* Header */}
        <div className="text-center mb-6">
          <div className="w-16 h-16 bg-blue-100 rounded-full flex items-center justify-center mx-auto mb-4">
            <Edit2 className="w-8 h-8 text-blue-600" />
          </div>
          <h3 className="text-2xl font-bold text-gray-900 mb-2">{t('training.editMetadata.title')}</h3>
          <p className="text-gray-600">{t('training.editMetadata.subtitle')}</p>
        </div>

        <div className="mb-4">
          <label className="block text-sm font-medium text-gray-700 mb-2">{t('training.editMetadata.slideId')}</label>
          <input
            type="text"
            value={editingWSI.wsi_id}
            disabled
            className="w-full px-4 py-2 border border-gray-300 rounded-lg bg-gray-50 text-gray-500 cursor-not-allowed"
          />
        </div>

        {isSurvival ? (
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">{t('training.editMetadata.timeMonths')}</label>
              <input
                type="number"
                step="0.01"
                value={eventTime}
                onChange={(e) => setEventTime(e.target.value)}
                placeholder={t('training.editMetadata.timePlaceholder')}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">{t('training.editMetadata.status01')}</label>
              <input
                type="number"
                min="0"
                max="1"
                step="1"
                value={eventStatus}
                onChange={(e) => setEventStatus(e.target.value)}
                placeholder={t('training.editMetadata.statusPlaceholder')}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              />
            </div>
          </div>
        ) : !isSegmentation ? (
          <div className="mb-4">
            <label className="block text-sm font-medium text-gray-700 mb-2">{labelHint}</label>
            <input
              type="text"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder={t('training.editMetadata.labelPlaceholder')}
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
          </div>
        ) : null}

        <div className="mb-4">
          <label className="block text-sm font-medium text-gray-700 mb-2">{t('training.editMetadata.caseId')}</label>
          <input
            type="text"
            value={caseId}
            onChange={(e) => setCaseId(e.target.value)}
            placeholder={t('training.editMetadata.caseIdPlaceholder')}
            className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          />
        </div>

        <div className="mb-4">
          <label className="block text-sm font-medium text-gray-700 mb-2">{t('training.editMetadata.age')}</label>
          <input
            type="number"
            value={age}
            onChange={(e) => setAge(e.target.value)}
            placeholder={t('training.editMetadata.agePlaceholder')}
            className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          />
        </div>

        <div className="mb-4">
          <label className="block text-sm font-medium text-gray-700 mb-2">{t('training.editMetadata.gender')}</label>
          <input
            type="text"
            value={gender}
            onChange={(e) => setGender(e.target.value)}
            placeholder={t('training.editMetadata.genderPlaceholder')}
            className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          />
        </div>


        <div className="flex gap-3">
          <button
            onClick={onCancel}
            disabled={updating}
            className="flex-1 px-6 py-2.5 text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors font-medium disabled:opacity-50"
          >
            {t('common.cancel')}
          </button>
          <button
            onClick={handleSubmit}
            disabled={updating}
            className="flex-1 px-6 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors font-semibold disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {updating ? t('training.editMetadata.updating') : t('training.editMetadata.saveChanges')}
          </button>
        </div>
      </div>
    </div>
  )
}
