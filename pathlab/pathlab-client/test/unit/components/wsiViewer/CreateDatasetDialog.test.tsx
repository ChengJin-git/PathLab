import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { CreateDatasetDialog } from '@renderer/components/wsiViewer/CreateDatasetDialog'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('@renderer/components/ui/tooltip', () => ({
  Tooltip: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

const baseProps = {
  show: true,
  onClose: vi.fn(),
  allAnnotations: {
    wsi_1: [
      {
        id: 'roi_1',
        type: 'rect' as const,
        x: 10,
        y: 20,
        width: 30,
        height: 40,
        label: 'tumor',
        color: '#ff0000',
      },
    ],
  },
  labelColors: { tumor: '#ff0000' },
  hasWsiSources: false,
  onSubmitCreateDataset: vi.fn(async () => {}),
}

describe('CreateDatasetDialog', () => {
  it('creates classification ROI datasets as patch classification datasets', async () => {
    const onSubmitCreateDataset = vi.fn(async () => {})

    render(
      <CreateDatasetDialog
        {...baseProps}
        onSubmitCreateDataset={onSubmitCreateDataset}
      />,
    )

    fireEvent.change(screen.getByLabelText('annotation.datasetName'), {
      target: { value: 'Tumor ROIs' },
    })
    fireEvent.click(screen.getByText('annotation.createConfirm'))

    await waitFor(() => expect(onSubmitCreateDataset).toHaveBeenCalledTimes(1))
    expect(onSubmitCreateDataset).toHaveBeenCalledWith({
      datasetName: 'Tumor ROIs',
      taskType: 'patch_classification',
      sourceOrgan: '',
    })
  })
})
