/**
 * EditMetadataModal Component
 *
 * Modal for editing metadata of a single slide.
 */

import React, { useState, useEffect } from 'react'
import { Edit2 } from 'lucide-react'
import { TaskType } from '../../types/training'

export interface WSIEditInfo {
  wsi_id: string
  label?: string
  case_id?: string
  age?: number
  gender?: string
  source?: string
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
    source: string
    event_time: string
    event_status: string
  }) => void
  onCancel: () => void
}

export function EditMetadataModal({ taskType, editingWSI, updating, onConfirm, onCancel }: EditMetadataModalProps) {
  const [label, setLabel] = useState('')
  const [caseId, setCaseId] = useState('')
  const [age, setAge] = useState('')
  const [gender, setGender] = useState('')
  const [source, setSource] = useState('')
  const [eventTime, setEventTime] = useState('')
  const [eventStatus, setEventStatus] = useState('')

  // Initialize form when editingWSI changes
  useEffect(() => {
    setLabel(editingWSI.label || '')
    setCaseId(editingWSI.case_id || '')
    setAge(editingWSI.age?.toString() || '')
    setGender(editingWSI.gender || '')
    setSource(editingWSI.source || '')
    setEventTime(editingWSI.event_time?.toString() || '')
    setEventStatus(editingWSI.event_status?.toString() || '')
  }, [editingWSI])

  const handleSubmit = () => {
    onConfirm({ label, case_id: caseId, age, gender, source, event_time: eventTime, event_status: eventStatus })
  }

  const isSurvival = taskType === 'survival_prediction'
  const labelHint = 'Label (Disease Classification)'

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full p-6">
        {/* Header */}
        <div className="text-center mb-6">
          <div className="w-16 h-16 bg-blue-100 rounded-full flex items-center justify-center mx-auto mb-4">
            <Edit2 className="w-8 h-8 text-blue-600" />
          </div>
          <h3 className="text-2xl font-bold text-gray-900 mb-2">Edit Metadata</h3>
          <p className="text-gray-600">Update slide information</p>
        </div>

        {/* Slide ID (read-only) */}
        <div className="mb-4">
          <label className="block text-sm font-medium text-gray-700 mb-2">Slide ID</label>
          <input
            type="text"
            value={editingWSI.wsi_id}
            disabled
            className="w-full px-4 py-2 border border-gray-300 rounded-lg bg-gray-50 text-gray-500 cursor-not-allowed"
          />
        </div>

        {/* Conditional Inputs: Survival vs Classification */}
        {isSurvival ? (
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Time (Months)</label>
              <input
                type="number"
                step="0.01"
                value={eventTime}
                onChange={(e) => setEventTime(e.target.value)}
                placeholder="e.g. 12.5"
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Status (0/1)</label>
              <input
                type="number"
                min="0"
                max="1"
                step="1"
                value={eventStatus}
                onChange={(e) => setEventStatus(e.target.value)}
                placeholder="0=Censored, 1=Event"
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              />
            </div>
          </div>
        ) : (
          /* Label Input (Classification) */
          <div className="mb-4">
            <label className="block text-sm font-medium text-gray-700 mb-2">{labelHint}</label>
            <input
              type="text"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="e.g., Benign, Malignant"
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
          </div>
        )}

        {/* Case ID Input */}
        <div className="mb-4">
          <label className="block text-sm font-medium text-gray-700 mb-2">Case ID</label>
          <input
            type="text"
            value={caseId}
            onChange={(e) => setCaseId(e.target.value)}
            placeholder="e.g., case_001"
            className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          />
        </div>

        {/* Age Input */}
        <div className="mb-4">
          <label className="block text-sm font-medium text-gray-700 mb-2">Age</label>
          <input
            type="number"
            value={age}
            onChange={(e) => setAge(e.target.value)}
            placeholder="e.g., 45"
            className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          />
        </div>

        {/* Gender Input */}
        <div className="mb-4">
          <label className="block text-sm font-medium text-gray-700 mb-2">Gender</label>
          <input
            type="text"
            value={gender}
            onChange={(e) => setGender(e.target.value)}
            placeholder="e.g., Male, Female"
            className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          />
        </div>

        {/* Source Input */}
        <div className="mb-6">
          <label className="block text-sm font-medium text-gray-700 mb-2">Source (Organ/Tissue)</label>
          <input
            type="text"
            value={source}
            onChange={(e) => setSource(e.target.value)}
            placeholder="e.g., Cervix, Lung, Breast"
            className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          />
        </div>

        {/* Action Buttons */}
        <div className="flex gap-3">
          <button
            onClick={onCancel}
            disabled={updating}
            className="flex-1 px-6 py-2.5 text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors font-medium disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={updating}
            className="flex-1 px-6 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors font-semibold disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {updating ? 'Updating...' : 'Save Changes'}
          </button>
        </div>
      </div>
    </div>
  )
}

