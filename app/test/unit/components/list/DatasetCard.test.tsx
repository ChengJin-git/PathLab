import { describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { DatasetCard } from '@renderer/components/list/DatasetCard'
import { TooltipProvider } from '@renderer/components/ui/tooltip'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

const mockDataset = {
  dataset_id: 'ds-1',
  dataset_name: 'Test Dataset Name',
  user_id: 'user-1',
  file_count: 42,
  total_size: 1024000,
  data_type: 'wsi' as const,
  task_types: ['wsi_classification' as const],
  metadata: {}, revision: 1, tasks: [],
  aggregation_level: 'file' as const,
  can_delete: true,
  username: 'testuser',
}

function renderCard(props: Partial<Parameters<typeof DatasetCard>[0]> = {}) {
  return render(
    <TooltipProvider>
      <DatasetCard
        dataset={mockDataset}
        itemType="slides"
        normalizedTaskType="classification"
        sourceOrganLabel="Liver"
        sourceOrganValue="Liver"
        isDeleting={false}
        isAdmin={false}
        onClick={vi.fn()}
        {...props}
      />
    </TooltipProvider>,
  )
}

describe('DatasetCard', () => {
  it('renders title and file count', () => {
    renderCard()
    expect(screen.getByText('Test Dataset Name')).toBeInTheDocument()
    expect(screen.getByText('42')).toBeInTheDocument()
  })

  it('calls onClick when the card is clicked', () => {
    const onClick = vi.fn()
    renderCard({ onClick })
    fireEvent.click(screen.getByTestId('dataset-card'))
    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('applies two-line title clamp class', () => {
    renderCard()
    const title = screen.getByTestId('dataset-card-title')
    expect(title.className).toContain('line-clamp-2')
  })

  it('applies constrained badge area class', () => {
    renderCard()
    const badgeZone = screen.getByTestId('dataset-card-badges')
    expect(badgeZone.className).toContain('dataset-card-badge-zone')
  })

  it('applies wider owner-name max-width', () => {
    renderCard({ isAdmin: true })
    const owner = screen.getByTestId('dataset-card-owner')
    expect(owner.className).toContain('max-w-[120px]')
    expect(owner.className).toContain('sm:max-w-[180px]')
  })

  it('lets the owner metadata shrink without hugging the footer edge', () => {
    renderCard({
      isAdmin: true,
      dataset: {
        ...mockDataset,
        username: 'PWH Tester Long Name',
      },
    })

    const ownerWrap = screen.getByTestId('dataset-card-owner').parentElement
    expect(ownerWrap?.className).toContain('min-w-0')
    expect(ownerWrap?.className).toContain('pl-2')
    expect(ownerWrap?.className).toContain('sm:pl-3')
  })

  it('does not render the chevron affordance as a focusable button', () => {
    renderCard()
    expect(screen.getAllByRole('button')).toHaveLength(3)
  })
})
