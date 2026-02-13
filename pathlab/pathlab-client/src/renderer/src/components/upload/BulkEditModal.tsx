import React from 'react'
import { X, Settings2 } from 'lucide-react'
import { Button } from '../ui/button'
import type { UploadMode, FileMetadata } from './types'
import { organSources } from './types'

export interface BulkEditModalProps {
  uploadMode: UploadMode
  selectedCount: number
  batchMetadata: FileMetadata
  onBatchMetadataChange: (updater: (prev: FileMetadata) => FileMetadata) => void
  onApply: () => void
  onClose: () => void
}

export const BulkEditModal: React.FC<BulkEditModalProps> = ({
  uploadMode, selectedCount, batchMetadata, onBatchMetadataChange, onApply, onClose
}) => {
  return (
    <div className="fixed inset-0 z-[100] bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-white rounded-[1.5rem] sm:rounded-3xl shadow-2xl w-full max-w-lg p-5 sm:p-8 animate-in zoom-in-95 duration-200">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h3 className="text-lg sm:text-xl font-bold text-slate-900 flex items-center gap-2">
              <Settings2 className="w-5 h-5 text-blue-600" />
              Batch Edit
            </h3>
            <p className="text-xs sm:text-sm text-slate-500 mt-1">{selectedCount} items selected</p>
          </div>
          <button onClick={onClose} className="p-2 text-slate-400 hover:text-slate-600 rounded-full hover:bg-slate-100 transition-colors">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="space-y-4 sm:space-y-6">
          {/* Classification: Label | Survival: Event Time & Status */}
          {uploadMode === 'classification' ? (
            <div className="space-y-1.5">
              <label className="text-[10px] sm:text-xs font-semibold text-slate-500 uppercase tracking-wider">Label</label>
              <input
                className="w-full px-3 py-2 border border-slate-200 rounded-xl text-sm focus:ring-4 focus:ring-blue-500/10 focus:border-blue-500 outline-none transition-all"
                placeholder="Apply label to all..."
                value={batchMetadata.label}
                onChange={e => onBatchMetadataChange(p => ({ ...p, label: e.target.value }))}
              />
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-3 sm:gap-4">
              <div className="space-y-1.5">
                <label className="text-[10px] sm:text-xs font-semibold text-emerald-600 uppercase tracking-wider">Event Time</label>
                <input
                  type="number"
                  step="0.1"
                  className="w-full px-3 py-2 border border-slate-200 rounded-xl text-sm focus:ring-4 focus:ring-emerald-500/10 focus:border-emerald-500 outline-none"
                  placeholder="Months..."
                  value={batchMetadata.event_time}
                  onChange={e => onBatchMetadataChange(p => ({ ...p, event_time: e.target.value }))}
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-[10px] sm:text-xs font-semibold text-emerald-600 uppercase tracking-wider">Status</label>
                <select
                  className="w-full px-3 py-2 border border-slate-200 rounded-xl text-sm focus:ring-4 focus:ring-emerald-500/10 focus:border-emerald-500 outline-none"
                  value={batchMetadata.event_status}
                  onChange={e => onBatchMetadataChange(p => ({ ...p, event_status: e.target.value }))}
                >
                  <option value="">No Change</option>
                  <option value="1">Event (1)</option>
                  <option value="0">Censored (0)</option>
                </select>
              </div>
            </div>
          )}
          <div className="grid grid-cols-2 gap-3 sm:gap-4">
            <div className="space-y-1.5">
              <label className="text-[10px] sm:text-xs font-semibold text-slate-500 uppercase tracking-wider">Case ID</label>
              <input
                className="w-full px-3 py-2 border border-slate-200 rounded-xl text-sm focus:ring-4 focus:ring-blue-500/10 focus:border-blue-500 outline-none"
                placeholder="Batch ID"
                value={batchMetadata.case_id}
                onChange={e => onBatchMetadataChange(p => ({ ...p, case_id: e.target.value }))}
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-[10px] sm:text-xs font-semibold text-slate-500 uppercase tracking-wider">Age</label>
              <input
                type="number"
                className="w-full px-3 py-2 border border-slate-200 rounded-xl text-sm focus:ring-4 focus:ring-blue-500/10 focus:border-blue-500 outline-none"
                placeholder="Age"
                value={batchMetadata.age}
                onChange={e => onBatchMetadataChange(p => ({ ...p, age: e.target.value }))}
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3 sm:gap-4">
            <div className="space-y-1.5">
              <label className="text-[10px] sm:text-xs font-semibold text-slate-500 uppercase tracking-wider">Source</label>
              <select
                className="w-full px-3 py-2 border border-slate-200 rounded-xl text-sm focus:ring-4 focus:ring-blue-500/10 focus:border-blue-500 outline-none"
                value={batchMetadata.source}
                onChange={e => onBatchMetadataChange(p => ({ ...p, source: e.target.value }))}
              >
                <option value="">No Change</option>
                {organSources.map(o => <option key={o} value={o}>{o}</option>)}
              </select>
            </div>
            <div className="space-y-1.5">
              <label className="text-[10px] sm:text-xs font-semibold text-slate-500 uppercase tracking-wider">Gender</label>
              <select
                className="w-full px-3 py-2 border border-slate-200 rounded-xl text-sm focus:ring-4 focus:ring-blue-500/10 focus:border-blue-500 outline-none"
                value={batchMetadata.gender}
                onChange={e => onBatchMetadataChange(p => ({ ...p, gender: e.target.value }))}
              >
                <option value="">No Change</option>
                <option value="Male">Male</option>
                <option value="Female">Female</option>
                <option value="Unspecified">Any</option>
              </select>
            </div>
          </div>
        </div>

        <div className="mt-8 flex flex-col sm:flex-row justify-end gap-3">
          <Button variant="ghost" className="h-11 sm:h-10 order-2 sm:order-1 font-semibold" onClick={onClose}>Cancel</Button>
          <Button onClick={onApply} className="bg-blue-600 hover:bg-blue-700 text-white h-11 sm:h-10 shadow-lg shadow-blue-500/20 order-1 sm:order-2 font-semibold">Apply Changes</Button>
        </div>
      </div>
    </div>
  )
}

