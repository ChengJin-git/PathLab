import React from 'react'
import { Layers, Database, Info } from 'lucide-react'
import { Label } from '../../ui/label'

interface DataLevelSelectionProps {
  batchDataLevel: 'case' | 'file'
  setBatchDataLevel: (level: 'case' | 'file') => void
}

export const DataLevelSelection: React.FC<DataLevelSelectionProps> = ({ batchDataLevel, setBatchDataLevel }) => (
  <div className="bg-slate-50 rounded-lg p-4 space-y-3 border border-slate-200">
    <Label className="text-sm font-medium text-slate-900 block">Data Level</Label>
    <div className="flex gap-2">
      <button
        type="button"
        onClick={() => setBatchDataLevel('file')}
        className={`flex-1 px-4 py-2.5 rounded-lg text-sm font-medium transition-all ${
          batchDataLevel === 'file'
            ? 'bg-primary-100 text-primary-900 border-2 border-primary-300 shadow-sm'
            : 'bg-white text-gray-500 border border-gray-100 hover:border-primary-200 hover:text-primary-600'
        }`}
      >
        <div className="flex items-center justify-center gap-2">
          <Layers className={`w-4 h-4 ${batchDataLevel === 'file' ? 'text-primary-700' : 'text-gray-400'}`} />
          File-Level
        </div>
      </button>
      <button
        type="button"
        onClick={() => setBatchDataLevel('case')}
        className={`flex-1 px-4 py-2.5 rounded-lg text-sm font-medium transition-all ${
          batchDataLevel === 'case'
            ? 'bg-primary-100 text-primary-900 border-2 border-primary-300 shadow-sm'
            : 'bg-white text-gray-500 border border-gray-100 hover:border-primary-200 hover:text-primary-600'
        }`}
      >
        <div className="flex items-center justify-center gap-2">
          <Database className={`w-4 h-4 ${batchDataLevel === 'case' ? 'text-primary-700' : 'text-gray-400'}`} />
          Case-Level
        </div>
      </button>
    </div>

    {/* Info message based on data level */}
    <div className="flex items-start gap-2 p-3 bg-white rounded-lg border border-slate-100">
      <Info className="w-4 h-4 text-primary-500 mt-0.5 flex-shrink-0" />
      <div className="text-xs text-gray-600">
        {batchDataLevel === 'file' ? (
          <>
            Each file is treated as an <span className="font-medium text-gray-800">independent sample</span>.
            <br />
            Suitable for file-level classification or survival analysis.
          </>
        ) : (
          <>
            Files are grouped by <span className="font-medium text-gray-800">case ID</span> (extracted from filename).
            <br />
            Suitable for case-level survival analysis where multiple files share the same outcome.
          </>
        )}
      </div>
    </div>
  </div>
)

