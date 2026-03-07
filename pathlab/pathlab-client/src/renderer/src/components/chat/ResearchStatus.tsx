/**
 * Research Status Component
 * Displays real-time progress of deep research operations
 */

import React from 'react'
import { Search, Loader2, CheckCircle2, FileText, X } from 'lucide-react'
import { Card } from '../ui/card'
import { Button } from '../ui/button'

export interface ResearchStatusData {
  stage: string // "searching", "compressing", "writing", "starting", etc.
  topic?: string
  snippet?: string
  source?: string
}

interface ResearchStatusProps {
  status: ResearchStatusData | null
  searchResults: Array<{ topic: string; snippet: string }>
  isActive: boolean
  researchStatus?: 'idle' | 'awaiting_user' | 'running' | 'done'
  onReset?: () => void
}

export function ResearchStatus({ status, searchResults, isActive, researchStatus, onReset }: ResearchStatusProps) {
  if (!isActive && searchResults.length === 0 && researchStatus === 'idle') {
    return null
  }

  const getStageIcon = (stage: string) => {
    switch (stage) {
      case 'starting':
        return <Loader2 className="w-4 h-4 animate-spin text-blue-500" />
      case 'searching':
        return <Search className="w-4 h-4 animate-pulse text-blue-500" />
      case 'compressing':
      case 'writing':
        return <Loader2 className="w-4 h-4 animate-spin text-orange-500" />
      case 'done':
        return <CheckCircle2 className="w-4 h-4 text-green-500" />
      case 'clarifying':
      case 'confirming':
      case 'awaiting':
        return <FileText className="w-4 h-4 text-purple-500" />
      default:
        return <FileText className="w-4 h-4" />
    }
  }

  const getStageText = (stage: string) => {
    switch (stage) {
      case 'starting':
        return 'Starting research...'
      case 'searching':
        return 'Searching...'
      case 'compressing':
        return 'Analyzing results...'
      case 'writing':
        return 'Writing report...'
      case 'done':
        return 'Research complete'
      case 'clarifying':
        return 'Clarifying requirements...'
      case 'confirming':
        return 'Confirming research scope...'
      case 'awaiting':
        return 'Please respond to continue...'
      default:
        return stage.charAt(0).toUpperCase() + stage.slice(1)
    }
  }

  const getResearchStatusText = () => {
    switch (researchStatus) {
      case 'running':
        return 'Deep Research in Progress'
      case 'awaiting_user':
        return 'Awaiting Your Response'
      case 'done':
        return 'Research Completed'
      default:
        return 'Research Status'
    }
  }

  const getResearchStatusColor = () => {
    switch (researchStatus) {
      case 'running':
        return 'border-blue-200 bg-blue-50/50'
      case 'awaiting_user':
        return 'border-purple-200 bg-purple-50/50'
      case 'done':
        return 'border-green-200 bg-green-50/50'
      default:
        return 'border-blue-200 bg-blue-50/50'
    }
  }

  return (
    <Card className={`p-4 mb-4 ${getResearchStatusColor()}`}>
      <div className="space-y-3">
        {/* Research Status Header */}
        <div className="flex items-center justify-between text-sm font-medium text-gray-800">
          <div className="flex items-center gap-2">
            <Search className="w-4 h-4" />
            <span>{getResearchStatusText()}</span>
          </div>
          {onReset && (researchStatus === 'done' || researchStatus === 'awaiting_user') && (
            <Button
              variant="ghost"
              size="sm"
              onClick={onReset}
              className="h-6 w-6 p-0 hover:bg-gray-200"
              title="Clear research status"
            >
              <X className="w-3 h-3" />
            </Button>
          )}
        </div>

        {/* Current Stage Status */}
        {status && (
          <div className="flex items-center gap-2 text-sm">
            {getStageIcon(status.stage)}
            <span className="font-medium">{getStageText(status.stage)}</span>
            {status.topic && (
              <span className="text-gray-600 truncate max-w-md">
                {status.topic.length > 60 ? `${status.topic.substring(0, 60)}...` : status.topic}
              </span>
            )}
          </div>
        )}

        {/* Search Results */}
        {searchResults.length > 0 && (
          <div className="space-y-2">
            <div className="text-xs font-medium text-gray-600">
              Found {searchResults.length} result{searchResults.length !== 1 ? 's' : ''}
            </div>
            <div className="space-y-1 max-h-32 overflow-y-auto">
              {searchResults.slice(-5).map((result, idx) => (
                <div key={idx} className="text-xs text-gray-700 bg-white/50 p-2 rounded">
                  <div className="font-medium truncate">{result.topic}</div>
                  {result.snippet && (
                    <div className="text-gray-600 truncate mt-1">
                      {result.snippet.length > 100 ? `${result.snippet.substring(0, 100)}...` : result.snippet}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </Card>
  )
}
