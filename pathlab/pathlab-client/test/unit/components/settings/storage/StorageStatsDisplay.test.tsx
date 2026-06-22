import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { StorageStatsDisplay } from '../../../../../src/renderer/src/components/settings/storage/StorageStatsDisplay'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => {
      const translations: Record<string, string> = {
        'settings.storage.totalStorage': 'Total Storage',
        'settings.storage.totalFiles': 'Total Files',
        'settings.storage.acrossCategories': 'Across Categories',
        'settings.storage.storageLocation': 'Storage Location',
        'settings.storage.storageBreakdown': 'Storage Breakdown',
        'settings.storage.labelAIResultBundles': 'AI Results',
      }
      return translations[key] ?? key
    },
  }),
}))

describe('StorageStatsDisplay', () => {
  it('renders ai_result_bundles with the settings storage translation', () => {
    render(
      <StorageStatsDisplay
        stats={{
          total_size_mb: 1,
          total_size_gb: 0.001,
          uploads_dir: '/tmp/pathlab/uploads',
          breakdown: {
            ai_result_bundles: { file_count: 2, size: 2048 },
          },
        }}
        formatFileSize={(bytes) => `${bytes} B`}
      />
    )

    expect(screen.getByText('AI Results')).toBeInTheDocument()
    expect(screen.queryByText('ai_result_bundles')).not.toBeInTheDocument()
  })
})
