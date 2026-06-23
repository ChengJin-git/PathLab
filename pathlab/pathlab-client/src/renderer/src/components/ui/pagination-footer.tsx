import React from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { Button } from './button'
import { Select } from './select'

const DEFAULT_PAGE_SIZE_OPTIONS = ['4', '6', '9', '18']

interface PaginationFooterProps {
  page: number
  pageSize: number
  total: number
  disabled?: boolean
  pageSizeOptions?: string[]
  onPageChange: (page: number) => void
  onPageSizeChange: (pageSize: number) => void
}

export function PaginationFooter({
  page,
  pageSize,
  total,
  disabled,
  pageSizeOptions = DEFAULT_PAGE_SIZE_OPTIONS,
  onPageChange,
  onPageSizeChange,
}: PaginationFooterProps) {
  const { t } = useTranslation()
  const totalPages = Math.max(1, Math.ceil(total / pageSize) || 1)

  return (
    <div className="flex flex-col gap-3 border-t border-gray-200 pt-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-2 text-sm text-gray-600">
        <span>{t('settings.permissionCenterModal.itemsPerPage')}</span>
        <Select
          value={String(pageSize)}
          onChange={(value) => onPageSizeChange(Number(value))}
          options={pageSizeOptions.map((value) => ({ value, label: value }))}
          className="w-20"
          disabled={disabled}
        />
      </div>
      <div className="flex items-center justify-between gap-3 sm:justify-end">
        <span className="text-sm text-gray-500">
          {t('settings.permissionCenterModal.pageInfo', {
            current: Math.min(page, totalPages),
            total: totalPages,
            count: total,
          })}
        </span>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => onPageChange(page - 1)}
            disabled={disabled || page <= 1}
            className="gap-1"
          >
            <ChevronLeft className="h-3.5 w-3.5" />
            {t('settings.permissionCenterModal.previous')}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => onPageChange(page + 1)}
            disabled={disabled || page >= totalPages}
            className="gap-1"
          >
            {t('settings.permissionCenterModal.next')}
            <ChevronRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    </div>
  )
}
