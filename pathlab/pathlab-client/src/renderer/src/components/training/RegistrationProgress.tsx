/**
 * RegistrationProgress Component
 *
 * Displays progress of file registration/upload.
 */

import React from 'react'
import { Loader2, CheckCircle2, AlertCircle } from 'lucide-react'
import { UploadingFileStatus } from '../../types/training'

export interface RegistrationProgressProps {
  uploadingFiles: Map<string, UploadingFileStatus>
}

export function RegistrationProgress({ uploadingFiles }: RegistrationProgressProps) {
  const successCount = Array.from(uploadingFiles.values()).filter((f) => f.status === 'success').length

  return (
    <div className="mb-6 bg-gray-50/50 rounded-xl border border-gray-100 p-4 sm:p-6">
      <h3 className="text-sm sm:text-base font-bold text-gray-900 mb-4">
        Registering Files ({successCount}/{uploadingFiles.size})
      </h3>
      <div className="space-y-4">
        {Array.from(uploadingFiles.entries()).map(([fileName, fileStatus]) => (
          <div key={fileName} className="space-y-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 flex-1 min-w-0">
                {fileStatus.status === 'uploading' && <Loader2 className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-primary-600 animate-spin" />}
                {fileStatus.status === 'success' && <CheckCircle2 className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-green-500" />}
                {fileStatus.status === 'error' && <AlertCircle className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-red-500" />}
                <span className="text-xs sm:text-sm font-medium text-gray-900 truncate">{fileName}</span>
              </div>
              <span
                className={`text-[10px] sm:text-xs font-bold leading-none ${
                  fileStatus.status === 'success' ? 'text-green-600' : fileStatus.status === 'error' ? 'text-red-600' : 'text-primary-600'
                }`}
              >
                {fileStatus.status === 'uploading' && `${Math.round(fileStatus.progress)}%`}
                {fileStatus.status === 'success' && 'DONE'}
                {fileStatus.status === 'error' && 'FAILED'}
              </span>
            </div>
            {/* Progress Bar */}
            <div className="w-full bg-gray-200 rounded-full h-1.5 overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-300 ${
                  fileStatus.status === 'success' ? 'bg-green-500' : fileStatus.status === 'error' ? 'bg-red-500' : 'bg-primary-500'
                }`}
                style={{ width: `${fileStatus.progress}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

