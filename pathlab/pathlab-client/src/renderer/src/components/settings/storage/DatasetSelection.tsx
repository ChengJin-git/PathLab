import React from 'react'
import { Plus, Database } from 'lucide-react'
import { Input } from '../../ui/input'
import { Select } from '../../ui/select'
import { Label } from '../../ui/label'
import { DatasetSummary } from '../../../api'

interface DatasetSelectionProps {
  batchDatasetMode: 'existing' | 'new'
  setBatchDatasetMode: (mode: 'existing' | 'new') => void
  batchSelectedDatasetId: string
  setBatchSelectedDatasetId: (id: string) => void
  batchNewDatasetNameRef: React.RefObject<HTMLInputElement>
  batchDatasets: DatasetSummary[]
}

export const DatasetSelection: React.FC<DatasetSelectionProps> = ({
  batchDatasetMode,
  setBatchDatasetMode,
  batchSelectedDatasetId,
  setBatchSelectedDatasetId,
  batchNewDatasetNameRef,
  batchDatasets
}) => (
  <div className="bg-gray-50 rounded-lg p-4 space-y-3">
    <Label className="text-sm font-medium text-gray-700 block">Dataset</Label>
    <div className="flex gap-2">
      <button
        type="button"
        onClick={() => setBatchDatasetMode('new')}
        className={`flex-1 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
          batchDatasetMode === 'new'
            ? 'bg-primary-600 text-white shadow-md'
            : 'bg-white text-gray-600 border border-gray-200 hover:border-primary-300 hover:text-primary-600'
        }`}
      >
        <div className="flex items-center justify-center gap-2">
          <Plus className="w-4 h-4" />
          Create New
        </div>
      </button>
      <button
        type="button"
        onClick={() => setBatchDatasetMode('existing')}
        className={`flex-1 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
          batchDatasetMode === 'existing'
            ? 'bg-primary-600 text-white shadow-md'
            : 'bg-white text-gray-600 border border-gray-200 hover:border-primary-300 hover:text-primary-600'
        }`}
      >
        <div className="flex items-center justify-center gap-2">
          <Database className="w-4 h-4" />
          Add to Existing
        </div>
      </button>
    </div>

    {batchDatasetMode === 'new' ? (
      <Input
        ref={batchNewDatasetNameRef}
        placeholder="Enter new dataset name..."
      />
    ) : (
      <Select
        value={batchSelectedDatasetId}
        onChange={(value) => setBatchSelectedDatasetId(value)}
        options={[
          { value: '', label: 'Select a dataset...' },
          ...batchDatasets.filter(d => d.dataset_id !== null).map(d => ({ value: d.dataset_id!, label: d.dataset_name }))
        ]}
      />
    )}
  </div>
)

