/**
 * WSIDataTable Component
 *
 * Data table for WSI/Patch file selection with grouping and pagination.
 */

import React from 'react'
import { Button } from '../ui/button'
import { Loader2, ChevronLeft, ChevronRight, ChevronDown, Edit2, Trash2, Users } from 'lucide-react'
import { TaskType } from '../../constants/training'

export interface WSIItem {
  wsi_id: string
  file_extension: string
  original_filename: string
  label?: string
  case_id?: string
  event_time?: number
  event_status?: number
  age?: number
  gender?: string
  source?: string
  file_size: number
  split?: string
}

export interface WSIDataTableProps {
  taskType: TaskType
  loading: boolean
  filteredItems: WSIItem[]
  pageSlides: WSIItem[]

  // Selection
  selectedIds: Set<string>
  allPageSelected: boolean
  allFilteredSelected: boolean
  handleSelectPage: () => void
  handleSelectAllFiltered: () => void
  toggleSelection: (id: string) => void
  setSelectedIds: (ids: Set<string>) => void

  // Case grouping
  hasMultiSlideCases: boolean
  paginatedCases: [string, WSIItem[]][] | null
  expandedCases: Set<string>
  toggleCaseExpansion: (caseId: string) => void
  isPatchDataset: boolean
  totalCases: number

  // Pagination
  currentPage: number
  setCurrentPage: (page: number) => void
  pageSize: number

  // Actions
  handleEditClick: (item: WSIItem) => void
  handleDeleteClick: (wsiId: string, label?: string, filename?: string) => void

  // Helpers
  getFileType: (fileExtension: string, size: number) => 'WSI' | 'Patch'
}

export function WSIDataTable({
  taskType,
  loading,
  filteredItems,
  pageSlides,
  selectedIds,
  allPageSelected,
  allFilteredSelected,
  handleSelectPage,
  handleSelectAllFiltered,
  toggleSelection,
  setSelectedIds,
  hasMultiSlideCases,
  paginatedCases,
  expandedCases,
  toggleCaseExpansion,
  isPatchDataset,
  totalCases,
  currentPage,
  setCurrentPage,
  pageSize,
  handleEditClick,
  handleDeleteClick,
  getFileType,
}: WSIDataTableProps) {
  return (
    <div className="space-y-4">
      <div className="bg-white border border-gray-100 rounded-xl overflow-hidden shadow-sm flex flex-col">
        <div className="overflow-x-auto scrollbar-none">
          <table className="w-full">
            <thead>
              <tr className={`h-[50px] bg-gray-50/80 border-b border-gray-100 backdrop-blur-md ${selectedIds.size > 0 ? 'bg-primary-50/50' : ''}`}>
                <th className="px-3 sm:px-6 py-3 text-left w-10 sm:w-12">
                  <input
                    type="checkbox"
                    checked={allPageSelected}
                    onChange={handleSelectPage}
                    className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded transition-colors"
                  />
                </th>
                {selectedIds.size > 0 ? (
                  <th colSpan={10} className="px-3 sm:px-6 py-3 text-left">
                    <div className="flex items-center gap-4">
                      <span className="text-xs sm:text-sm font-bold text-primary-900">{selectedIds.size} selected</span>
                      {selectedIds.size > 0 && !allFilteredSelected && (
                        <button onClick={() => setSelectedIds(new Set())} className="text-[10px] sm:text-xs font-medium text-gray-500 hover:text-gray-700 underline">
                          Clear selection
                        </button>
                      )}
                    </div>
                  </th>
                ) : (
                  <>
                    <th className="px-3 sm:px-6 py-3 text-left text-[10px] sm:text-xs font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">Slide ID</th>
                    <th className="px-3 sm:px-6 py-3 text-left text-[10px] sm:text-xs font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">Type</th>
                    {taskType === 'survival' ? (
                      <>
                        <th className="px-3 sm:px-6 py-3 text-left text-[10px] sm:text-xs font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">Time (M)</th>
                        <th className="px-3 sm:px-6 py-3 text-left text-[10px] sm:text-xs font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">Status</th>
                      </>
                    ) : (
                      <th className="px-3 sm:px-6 py-3 text-left text-[10px] sm:text-xs font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">Label</th>
                    )}
                    <th className="px-3 sm:px-6 py-3 text-left text-[10px] sm:text-xs font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">Patient Info</th>
                    <th className="px-3 sm:px-6 py-3 text-right text-[10px] sm:text-xs font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">Action</th>
                  </>
                )}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {/* Batch Selection Banners */}
              <BatchSelectionBanner
                allPageSelected={allPageSelected}
                allFilteredSelected={allFilteredSelected}
                pageCount={pageSlides.length}
                totalCount={filteredItems.length}
                onSelectAll={handleSelectAllFiltered}
                onClearSelection={() => setSelectedIds(new Set())}
              />

              {/* Table Content */}
              {loading ? (
                <tr>
                  <td colSpan={100} className="py-12 sm:py-20 text-center">
                    <Loader2 className="w-8 h-8 text-primary-600 animate-spin mx-auto mb-3" />
                    <span className="text-xs sm:text-sm text-gray-500 font-medium italic">Loading files...</span>
                  </td>
                </tr>
              ) : filteredItems.length === 0 ? (
                <tr>
                  <td colSpan={100} className="py-12 sm:py-20 text-center text-gray-500 italic text-xs sm:text-sm">
                    No files found.
                  </td>
                </tr>
              ) : (
                <TableContent {...{ taskType, hasMultiSlideCases, paginatedCases, pageSlides, selectedIds, toggleSelection, expandedCases, toggleCaseExpansion, isPatchDataset, handleEditClick, handleDeleteClick, getFileType, setSelectedIds }} />
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        <PaginationFooter
          currentPage={currentPage}
          setCurrentPage={setCurrentPage}
          pageSize={pageSize}
          totalCount={hasMultiSlideCases ? totalCases : filteredItems.length}
          itemLabel={hasMultiSlideCases ? 'Cases' : 'Items'}
        />
      </div>
    </div>
  )
}

/** Batch selection banner */
function BatchSelectionBanner({
  allPageSelected,
  allFilteredSelected,
  pageCount,
  totalCount,
  onSelectAll,
  onClearSelection,
}: {
  allPageSelected: boolean
  allFilteredSelected: boolean
  pageCount: number
  totalCount: number
  onSelectAll: () => void
  onClearSelection: () => void
}) {
  if (allPageSelected && !allFilteredSelected) {
    return (
      <tr className="bg-blue-50/50">
        <td colSpan={100} className="px-4 py-2 text-center text-xs sm:text-sm text-gray-700 border-b border-blue-100">
          <span className="font-medium">All {pageCount} items on this page are selected.</span>
          <button onClick={onSelectAll} className="ml-2 font-bold text-blue-600 hover:text-blue-800 hover:underline focus:outline-none">
            Select all {totalCount} items in list
          </button>
        </td>
      </tr>
    )
  }

  if (allFilteredSelected && totalCount > pageCount) {
    return (
      <tr className="bg-blue-50/50">
        <td colSpan={100} className="px-4 py-2 text-center text-xs sm:text-sm text-gray-700 border-b border-blue-100">
          <span className="font-medium">All {totalCount} items in list are selected.</span>
          <button onClick={onClearSelection} className="ml-2 font-bold text-blue-600 hover:text-blue-800 hover:underline focus:outline-none">
            Clear selection
          </button>
        </td>
      </tr>
    )
  }

  return null
}

/** Pagination footer */
function PaginationFooter({
  currentPage,
  setCurrentPage,
  pageSize,
  totalCount,
  itemLabel,
}: {
  currentPage: number
  setCurrentPage: (page: number) => void
  pageSize: number
  totalCount: number
  itemLabel: string
}) {
  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize))

  return (
    <div className="border-t border-gray-100 bg-gray-50/50 px-4 py-3 sm:px-6 sm:py-4 flex flex-col sm:flex-row items-center justify-between gap-3">
      <div className="text-[10px] sm:text-xs text-gray-500 font-medium">
        Showing <span className="font-bold text-gray-900">{Math.min(totalCount, (currentPage - 1) * pageSize + 1)}</span>-
        <span className="font-bold text-gray-900">{Math.min(currentPage * pageSize, totalCount)}</span> of
        <span className="font-bold text-gray-900 ml-1">
          {totalCount} {itemLabel}
        </span>
      </div>
      <div className="flex items-center gap-2">
        <button
          onClick={() => setCurrentPage(Math.max(1, currentPage - 1))}
          disabled={currentPage === 1 || totalCount === 0}
          className="p-1.5 sm:p-2 rounded-xl border bg-white enabled:hover:bg-gray-50 disabled:opacity-30 transition-all font-bold"
        >
          <ChevronLeft className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
        </button>
        <span className="text-[10px] sm:text-xs font-bold text-gray-600 px-2">
          {currentPage} / {totalPages}
        </span>
        <button
          onClick={() => setCurrentPage(Math.min(totalPages, currentPage + 1))}
          disabled={currentPage === totalPages || totalCount === 0}
          className="p-1.5 sm:p-2 rounded-xl border bg-white enabled:hover:bg-gray-50 disabled:opacity-30 transition-all font-bold"
        >
          <ChevronRight className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
        </button>
      </div>
    </div>
  )
}

/** Table content - handles grouped and flat views */
function TableContent({
  taskType,
  hasMultiSlideCases,
  paginatedCases,
  pageSlides,
  selectedIds,
  toggleSelection,
  expandedCases,
  toggleCaseExpansion,
  isPatchDataset,
  handleEditClick,
  handleDeleteClick,
  getFileType,
  setSelectedIds,
}: {
  taskType: TaskType
  hasMultiSlideCases: boolean
  paginatedCases: [string, WSIItem[]][] | null
  pageSlides: WSIItem[]
  selectedIds: Set<string>
  toggleSelection: (id: string) => void
  expandedCases: Set<string>
  toggleCaseExpansion: (caseId: string) => void
  isPatchDataset: boolean
  handleEditClick: (item: WSIItem) => void
  handleDeleteClick: (wsiId: string, label?: string, filename?: string) => void
  getFileType: (fileExtension: string, size: number) => 'WSI' | 'Patch'
  setSelectedIds: (ids: Set<string>) => void
}) {
  if (hasMultiSlideCases && paginatedCases) {
    return (
      <>
        {paginatedCases.map(([caseId, slides]) => (
          <CaseRow
            key={caseId}
            caseId={caseId}
            slides={slides}
            taskType={taskType}
            selectedIds={selectedIds}
            setSelectedIds={setSelectedIds}
            toggleSelection={toggleSelection}
            isExpanded={expandedCases.has(caseId)}
            toggleExpansion={() => toggleCaseExpansion(caseId)}
            handleEditClick={handleEditClick}
            handleDeleteClick={handleDeleteClick}
            getFileType={getFileType}
          />
        ))}
      </>
    )
  }

  // Flat view
  return (
    <>
      {pageSlides.map((item) => (
        <SlideRow
          key={item.wsi_id}
          item={item}
          taskType={taskType}
          isSelected={selectedIds.has(item.wsi_id)}
          onToggle={() => toggleSelection(item.wsi_id)}
          isPatchDataset={isPatchDataset}
          handleEditClick={handleEditClick}
          handleDeleteClick={handleDeleteClick}
          getFileType={getFileType}
        />
      ))}
    </>
  )
}

/** Single slide row */
function SlideRow({
  item,
  taskType,
  isSelected,
  onToggle,
  isPatchDataset,
  handleEditClick,
  handleDeleteClick,
  getFileType,
  nested = false,
}: {
  item: WSIItem
  taskType: TaskType
  isSelected: boolean
  onToggle: () => void
  isPatchDataset: boolean
  handleEditClick: (item: WSIItem) => void
  handleDeleteClick: (wsiId: string, label?: string, filename?: string) => void
  getFileType: (fileExtension: string, size: number) => 'WSI' | 'Patch'
  nested?: boolean
}) {
  const fileType = getFileType(item.file_extension, item.file_size)

  return (
    <tr
      className={`group transition-all duration-200 border-l-2 ${
        isSelected
          ? nested
            ? 'bg-blue-50/40 border-blue-400'
            : 'bg-blue-50/40 border-primary-500'
          : nested
            ? 'bg-gray-50/30 hover:bg-white/60 border-blue-200'
            : 'hover:bg-white/60 border-transparent hover:border-gray-200'
      }`}
    >
      <td className={`px-3 sm:px-6 py-${nested ? '3' : '4'} sm:py-${nested ? '4' : '5'} w-10 sm:w-12 ${nested ? 'pl-6 sm:pl-10' : ''}`}>
        <input
          type="checkbox"
          checked={isSelected}
          onChange={onToggle}
          className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded transition-colors"
        />
      </td>
      <td className={`px-3 sm:px-6 py-${nested ? '3' : '4'} sm:py-${nested ? '4' : '5'}`}>
        <div className={`flex flex-col min-w-[120px] sm:min-w-[150px] ${nested ? 'pl-4 sm:pl-6 min-h-[3rem]' : 'min-h-[3.5rem] sm:min-h-[4rem]'} justify-center`}>
          <span className={`${nested ? 'text-xs sm:text-sm font-medium text-gray-700' : 'text-sm sm:text-base font-semibold text-gray-900'} truncate max-w-[150px] sm:max-w-[200px]`} title={item.wsi_id}>
            {item.wsi_id}
          </span>
          <span className={`text-[10px] ${nested ? 'sm:text-xs text-gray-400' : 'sm:text-sm text-gray-500'} mt-0.5 truncate max-w-[150px] sm:max-w-[300px]`} title={item.original_filename}>
            {item.original_filename}
          </span>
          {item.case_id && !isPatchDataset && !nested && (
            <span className="text-[10px] sm:text-xs text-blue-600 mt-0.5 truncate max-w-[150px] sm:max-w-[200px]" title={`Case: ${item.case_id}`}>
              Case: {item.case_id}
            </span>
          )}
        </div>
      </td>
      <td className={`px-3 sm:px-6 py-${nested ? '3' : '4'} sm:py-${nested ? '4' : '5'}`}>
        {fileType === 'WSI' ? (
          <span className={`inline-flex items-center px-1.5 sm:px-${nested ? '2' : '2.5'} py-0.5 ${nested ? '' : 'sm:py-1'} rounded-md text-[10px] sm:text-xs font-medium bg-purple-100 text-purple-700 border border-purple-200 whitespace-nowrap`}>
            WSI
          </span>
        ) : (
          <span className={`inline-flex items-center px-1.5 sm:px-${nested ? '2' : '2.5'} py-0.5 ${nested ? '' : 'sm:py-1'} rounded-md text-[10px] sm:text-xs font-medium bg-green-100 text-green-700 border border-green-200 whitespace-nowrap`}>
            Patch
          </span>
        )}
      </td>
      {taskType === 'survival' ? (
        <>
          <td className={`px-3 sm:px-6 py-${nested ? '3' : '4'} sm:py-${nested ? '4' : '5'}`}>
            {item.event_time != null ? (
              <span className={`inline-flex items-center px-2 ${nested ? '' : 'sm:px-3'} py-0.5 ${nested ? '' : 'sm:py-1'} rounded-full text-xs ${nested ? '' : 'sm:text-sm'} font-medium bg-blue-100/80 text-blue-700 border border-blue-200/60 ${nested ? '' : 'shadow-sm'} whitespace-nowrap`}>
                {item.event_time}
              </span>
            ) : (
              <span className={`text-gray-300 text-[10px] ${nested ? '' : 'sm:text-sm'} italic`}>Not set</span>
            )}
          </td>
          <td className={`px-3 sm:px-6 py-${nested ? '3' : '4'} sm:py-${nested ? '4' : '5'}`}>
            {item.event_status != null ? (
              <span
                className={`inline-flex items-center px-2 ${nested ? '' : 'sm:px-3'} py-0.5 ${nested ? '' : 'sm:py-1'} rounded-full text-xs ${nested ? '' : 'sm:text-sm'} font-medium border ${nested ? '' : 'shadow-sm'} whitespace-nowrap ${
                  item.event_status === 1 ? 'bg-red-100/80 text-red-700 border-red-200/60' : 'bg-green-100/80 text-green-700 border-green-200/60'
                }`}
              >
                {item.event_status === 1 ? 'Event' : 'Censored'}
              </span>
            ) : (
              <span className={`text-gray-300 text-[10px] ${nested ? '' : 'sm:text-sm'} italic`}>Not set</span>
            )}
          </td>
        </>
      ) : (
        <td className={`px-3 sm:px-6 py-${nested ? '3' : '4'} sm:py-${nested ? '4' : '5'}`}>
          {item.label ? (
            <span className={`inline-flex items-center px-2 ${nested ? '' : 'sm:px-3'} py-0.5 ${nested ? '' : 'sm:py-1'} rounded-full text-xs ${nested ? '' : 'sm:text-sm'} font-medium bg-gray-100/80 text-gray-700 border border-gray-200/60 ${nested ? '' : 'shadow-sm'} whitespace-nowrap`}>
              {item.label}
            </span>
          ) : (
            <span className={`text-gray-300 text-[10px] ${nested ? '' : 'sm:text-sm'} italic`}>No Label</span>
          )}
        </td>
      )}
      <td className={`px-3 sm:px-6 py-${nested ? '3' : '4'} sm:py-${nested ? '4' : '5'}`}>
        <PatientInfoBadges item={item} nested={nested} />
      </td>
      <td className={`px-3 sm:px-6 py-${nested ? '3' : '4'} sm:py-${nested ? '4' : '5'} text-right`}>
        <div className={`flex items-center justify-end gap-1 ${nested ? 'sm:gap-2' : 'sm:gap-3'} ${nested ? '' : 'sm:'}opacity-60 group-hover:opacity-100 transition-opacity`}>
          <Button
            variant="ghost"
            size="icon"
            className={`h-${nested ? '6' : '7'} w-${nested ? '6' : '7'} sm:h-${nested ? '7' : '9'} sm:w-${nested ? '7' : '9'} text-gray-500 hover:text-gray-900 hover:bg-gray-100 rounded-lg`}
            title="Edit Metadata"
            onClick={(e) => {
              e.preventDefault()
              handleEditClick(item)
            }}
          >
            <Edit2 className={`w-${nested ? '3' : '3.5'} h-${nested ? '3' : '3.5'} sm:w-${nested ? '4' : '5'} sm:h-${nested ? '4' : '5'}`} />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className={`h-${nested ? '6' : '7'} w-${nested ? '6' : '7'} sm:h-${nested ? '7' : '9'} sm:w-${nested ? '7' : '9'} text-gray-500 hover:text-red-600 hover:bg-red-50 rounded-lg`}
            title="Delete File"
            onClick={(e) => {
              e.preventDefault()
              handleDeleteClick(item.wsi_id, item.label, item.original_filename)
            }}
          >
            <Trash2 className={`w-${nested ? '3' : '3.5'} h-${nested ? '3' : '3.5'} sm:w-${nested ? '4' : '5'} sm:h-${nested ? '4' : '5'}`} />
          </Button>
        </div>
      </td>
    </tr>
  )
}

/** Patient info badges */
function PatientInfoBadges({ item, nested }: { item: WSIItem; nested: boolean }) {
  if (!(item.age || item.gender || item.source)) {
    return <span className={`text-gray-300 text-[10px] ${nested ? '' : 'sm:text-sm'} italic`}>{nested ? '-' : 'Not specified'}</span>
  }

  return (
    <div className={`flex flex-wrap gap-1 ${nested ? '' : 'sm:gap-2'} items-center min-w-[${nested ? '80' : '100'}px]`}>
      {item.source && (
        <span className={`inline-flex items-center px-${nested ? '1.5' : '2'} ${nested ? '' : 'sm:px-3'} py-0.5 ${nested ? '' : 'sm:py-1'} rounded-md text-[10px] ${nested ? '' : 'sm:text-sm'} font-medium bg-blue-50 text-blue-700 border border-blue-100 whitespace-nowrap`}>
          {nested ? item.source : <><span className="hidden sm:inline">Source: </span><span className="sm:ml-1 text-blue-900">{item.source}</span></>}
        </span>
      )}
      {item.age && (
        <span className={`inline-flex items-center px-${nested ? '1.5' : '2'} ${nested ? '' : 'sm:px-3'} py-0.5 ${nested ? '' : 'sm:py-1'} rounded-md text-[10px] ${nested ? '' : 'sm:text-sm'} font-medium bg-gray-50 text-gray-700 border border-gray-200 whitespace-nowrap`}>
          {item.age}y
        </span>
      )}
      {item.gender && (
        <span className={`inline-flex items-center px-${nested ? '1.5' : '2'} ${nested ? '' : 'sm:px-3'} py-0.5 ${nested ? '' : 'sm:py-1'} rounded-md text-[10px] ${nested ? '' : 'sm:text-sm'} font-medium bg-gray-50 text-gray-700 border border-gray-200 whitespace-nowrap`}>
          {item.gender}
        </span>
      )}
    </div>
  )
}

/** Case row with expandable slides */
function CaseRow({
  caseId,
  slides,
  taskType,
  selectedIds,
  setSelectedIds,
  toggleSelection,
  isExpanded,
  toggleExpansion,
  handleEditClick,
  handleDeleteClick,
  getFileType,
}: {
  caseId: string
  slides: WSIItem[]
  taskType: TaskType
  selectedIds: Set<string>
  setSelectedIds: (ids: Set<string>) => void
  toggleSelection: (id: string) => void
  isExpanded: boolean
  toggleExpansion: () => void
  handleEditClick: (item: WSIItem) => void
  handleDeleteClick: (wsiId: string, label?: string, filename?: string) => void
  getFileType: (fileExtension: string, size: number) => 'WSI' | 'Patch'
}) {
  const isNoCase = caseId === '__no_case__'
  const isMultiSlide = slides.length > 1
  const allSelected = slides.every((s) => selectedIds.has(s.wsi_id))
  const someSelected = slides.some((s) => selectedIds.has(s.wsi_id))

  // For single-slide cases, render as simple row
  if (!isMultiSlide) {
    const item = slides[0]
    return (
      <SlideRow
        item={item}
        taskType={taskType}
        isSelected={selectedIds.has(item.wsi_id)}
        onToggle={() => toggleSelection(item.wsi_id)}
        isPatchDataset={false}
        handleEditClick={handleEditClick}
        handleDeleteClick={handleDeleteClick}
        getFileType={getFileType}
      />
    )
  }

  // Multi-slide case - render expandable group
  const handleCaseCheckbox = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newSelected = new Set(selectedIds)
    if (e.target.checked) {
      slides.forEach((s) => newSelected.add(s.wsi_id))
    } else {
      slides.forEach((s) => newSelected.delete(s.wsi_id))
    }
    setSelectedIds(newSelected)
  }

  // Get file types for the case
  const types = new Set(slides.map((s) => getFileType(s.file_extension, s.file_size)))
  const typeLabel = types.has('WSI') && types.has('Patch') ? 'Mixed' : types.values().next().value || 'WSI'

  return (
    <React.Fragment>
      {/* Case header row */}
      <tr
        className={`group transition-all duration-200 border-l-2 cursor-pointer ${
          someSelected ? 'bg-blue-50/40 border-primary-500' : 'hover:bg-gray-50/60 border-transparent hover:border-blue-200'
        }`}
        onClick={toggleExpansion}
      >
        <td className="px-3 sm:px-6 py-4 sm:py-5 w-10 sm:w-12" onClick={(e) => e.stopPropagation()}>
          <input
            type="checkbox"
            checked={allSelected}
            ref={(el) => {
              if (el) el.indeterminate = someSelected && !allSelected
            }}
            onChange={handleCaseCheckbox}
            className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 rounded transition-colors"
          />
        </td>
        <td className="px-3 sm:px-6 py-4 sm:py-5">
          <div className="flex items-center gap-2 sm:gap-3 min-h-[3.5rem] sm:min-h-[4rem]">
            <ChevronDown className={`w-4 h-4 sm:w-5 sm:h-5 text-gray-400 transition-transform ${isExpanded ? '' : '-rotate-90'}`} />
            <div className="flex flex-col sm:flex-row sm:items-center sm:gap-3">
              <div className="flex items-center gap-2">
                <Users className="w-4 h-4 sm:w-5 sm:h-5 text-blue-500" />
                <span className="text-sm sm:text-base font-semibold text-gray-900">{isNoCase ? 'No Case ID' : `Case: ${caseId}`}</span>
              </div>
              <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-700 border border-blue-200">
                {slides.length} slides
              </span>
            </div>
          </div>
        </td>
        <td className="px-3 sm:px-6 py-4 sm:py-5">
          <span
            className={`inline-flex items-center px-1.5 sm:px-2.5 py-0.5 sm:py-1 rounded-md text-[10px] sm:text-xs font-medium border whitespace-nowrap ${
              typeLabel === 'Mixed'
                ? 'bg-gray-100 text-gray-700 border-gray-200'
                : typeLabel === 'WSI'
                  ? 'bg-purple-100 text-purple-700 border-purple-200'
                  : 'bg-green-100 text-green-700 border-green-200'
            }`}
          >
            {typeLabel}
          </span>
        </td>
        <CaseLabelCell slides={slides} taskType={taskType} />
        <CasePatientInfoCell slides={slides} />
        <td className="px-3 sm:px-6 py-4 sm:py-5 text-right">
          <span className="text-xs text-gray-400 whitespace-nowrap">{isExpanded ? 'Collapse' : 'Expand'}</span>
        </td>
      </tr>

      {/* Expanded slides */}
      {isExpanded &&
        slides.map((item) => (
          <SlideRow
            key={item.wsi_id}
            item={item}
            taskType={taskType}
            isSelected={selectedIds.has(item.wsi_id)}
            onToggle={() => toggleSelection(item.wsi_id)}
            isPatchDataset={false}
            handleEditClick={handleEditClick}
            handleDeleteClick={handleDeleteClick}
            getFileType={getFileType}
            nested
          />
        ))}
    </React.Fragment>
  )
}

/** Case label cell */
function CaseLabelCell({ slides, taskType }: { slides: WSIItem[]; taskType: TaskType }) {
  if (taskType === 'survival') {
    const events = slides.filter((s) => s.event_status === 1).length
    const censored = slides.filter((s) => s.event_status === 0).length

    return (
      <>
        <td className="px-3 sm:px-6 py-4 sm:py-5">
          <span className="text-gray-400 text-xs italic">See slides</span>
        </td>
        <td className="px-3 sm:px-6 py-4 sm:py-5">
          {events === 0 && censored === 0 ? (
            <span className="text-gray-300 text-xs italic">Not set</span>
          ) : (
            <div className="flex flex-col gap-1">
              {events > 0 && (
                <span className="text-xs text-red-600 font-medium">
                  {events} Event{events > 1 ? 's' : ''}
                </span>
              )}
              {censored > 0 && <span className="text-xs text-green-600 font-medium">{censored} Censored</span>}
            </div>
          )}
        </td>
      </>
    )
  }

  const labels = Array.from(new Set(slides.map((s) => s.label).filter(Boolean)))

  return (
    <td className="px-3 sm:px-6 py-4 sm:py-5">
      {labels.length === 0 ? (
        <span className="text-gray-300 text-xs italic">No Label</span>
      ) : labels.length === 1 ? (
        <span className="inline-flex items-center px-2 sm:px-3 py-0.5 sm:py-1 rounded-full text-xs sm:text-sm font-medium bg-gray-100/80 text-gray-700 border border-gray-200/60 shadow-sm whitespace-nowrap">
          {labels[0]}
        </span>
      ) : (
        <div className="flex flex-wrap gap-1">
          {labels.slice(0, 2).map((l) => (
            <span key={l} className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-700 border border-gray-200">
              {l}
            </span>
          ))}
          {labels.length > 2 && <span className="text-xs text-gray-500">+{labels.length - 2}</span>}
        </div>
      )}
    </td>
  )
}

/** Case patient info cell */
function CasePatientInfoCell({ slides }: { slides: WSIItem[] }) {
  const sources = Array.from(new Set(slides.map((s) => s.source as string).filter(Boolean)))
  const ages = Array.from(new Set(slides.map((s) => s.age).filter((a): a is number => a !== null && a !== undefined)))
  const genders = Array.from(new Set(slides.map((s) => s.gender as string).filter(Boolean)))

  if (sources.length === 0 && ages.length === 0 && genders.length === 0) {
    return (
      <td className="px-3 sm:px-6 py-4 sm:py-5">
        <span className="text-gray-300 text-[10px] sm:text-sm italic">Not specified</span>
      </td>
    )
  }

  return (
    <td className="px-3 sm:px-6 py-4 sm:py-5">
      <div className="flex flex-wrap gap-1 sm:gap-2 items-center min-w-[100px]">
        {sources.length > 0 && (
          <span className="inline-flex items-center px-2 sm:px-3 py-0.5 sm:py-1 rounded-md text-[10px] sm:text-sm font-medium bg-blue-50 text-blue-700 border border-blue-100 whitespace-nowrap">
            {sources.length === 1 ? (
              <>
                <span className="hidden sm:inline">Source: </span>
                <span className="sm:ml-1 text-blue-900">{sources[0]}</span>
              </>
            ) : (
              `${sources.length} Sources`
            )}
          </span>
        )}
        {ages.length > 0 && (
          <span className="inline-flex items-center px-2 sm:px-3 py-0.5 sm:py-1 rounded-md text-[10px] sm:text-sm font-medium bg-gray-50 text-gray-700 border border-gray-200 whitespace-nowrap">
            {ages.length === 1 ? `${ages[0]}y` : `${Math.min(...ages)}..${Math.max(...ages)}y`}
          </span>
        )}
        {genders.length > 0 && (
          <span className="inline-flex items-center px-2 sm:px-3 py-0.5 sm:py-1 rounded-md text-[10px] sm:text-sm font-medium bg-gray-50 text-gray-700 border border-gray-200 whitespace-nowrap">
            {genders.length === 1 ? genders[0] : 'Mixed'}
          </span>
        )}
      </div>
    </td>
  )
}

