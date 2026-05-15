import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { TaskConfigCard, parseTaskConfig } from '@renderer/components/chat/TaskConfigCard'
import * as wsiApi from '@renderer/api/wsi'

vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: vi.fn() },
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('@renderer/contexts/BackgroundTaskContext', () => ({
  useBackgroundTask: () => ({ hasUploadingTasks: () => false }),
}))

vi.mock('@renderer/contexts/AuthContext', () => ({
  useAuth: () => ({ canUseGpuForDataset: () => true }),
}))

function LocationProbe() {
  const location = useLocation()

  return (
    <div
      data-testid="location-probe"
      data-pathname={location.pathname}
      data-state={JSON.stringify(location.state ?? null)}
    />
  )
}

function renderTaskConfigCard(props: Partial<React.ComponentProps<typeof TaskConfigCard>> = {}) {
  const defaultProps: React.ComponentProps<typeof TaskConfigCard> = {
    config: {
      task_name: 'Test Task',
      task_type: 'patch_classification',
      data_type: 'patch',
    },
  }
  return render(
    <MemoryRouter initialEntries={['/dashboard']}>
      <Routes>
        <Route
          path="/dashboard"
          element={(
            <>
              <TaskConfigCard {...defaultProps} {...props} />
              <LocationProbe />
            </>
          )}
        />
        <Route path="/register" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('parseTaskConfig', () => {
  it('accepts canonical patch segmentation chat configs', () => {
    const parsed = parseTaskConfig(`
      [TASK_CONFIG]
      {"task_name":"Segment","task_type":"patch_segmentation","data_type":"patch","seg_loss_names":["DiceLoss"]}
      [/TASK_CONFIG]
    `)

    expect(parsed?.task_type).toBe('patch_segmentation')
    expect(parsed?.data_type).toBe('patch')
  })

  it('accepts canonical patch classification chat configs', () => {
    const parsed = parseTaskConfig(`
      [TASK_CONFIG]
      {"task_name":"Classify patches","task_type":"patch_classification","data_type":"patch"}
      [/TASK_CONFIG]
    `)

    expect(parsed?.task_type).toBe('patch_classification')
    expect(parsed?.data_type).toBe('patch')
  })

  it('normalizes legacy classification patch chat configs before submission', () => {
    const parsed = parseTaskConfig(`
      [TASK_CONFIG]
      {"task_name":"Classify patches","task_type":"classification","data_type":"patch"}
      [/TASK_CONFIG]
    `)

    expect(parsed?.task_type).toBe('patch_classification')
    expect(parsed?.data_type).toBe('patch')
  })

  it('normalizes mismatched WSI classification patch chat configs before submission', () => {
    const parsed = parseTaskConfig(`
      [TASK_CONFIG]
      {"task_name":"Classify patches","task_type":"wsi_classification","data_type":"patch"}
      [/TASK_CONFIG]
    `)

    expect(parsed?.task_type).toBe('patch_classification')
    expect(parsed?.data_type).toBe('patch')
  })

  it('accepts canonical WSI survival chat configs', () => {
    const parsed = parseTaskConfig(`
      [TASK_CONFIG]
      {"task_name":"Survival","task_type":"wsi_survival","data_type":"wsi"}
      [/TASK_CONFIG]
    `)

    expect(parsed?.task_type).toBe('wsi_survival')
    expect(parsed?.data_type).toBe('wsi')
  })

  it('does not normalize legacy chat task families', () => {
    const parsed = parseTaskConfig(`
      [TASK_CONFIG]
      {"task_name":"Legacy","task_type":"segmentation","data_type":"wsi"}
      [/TASK_CONFIG]
    `)

    expect(parsed?.task_type).toBe('wsi_classification')
    expect(parsed?.data_type).toBe('wsi')
  })
})

describe('TaskConfigCard split CSV upload state/navigation', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('shows custom/manual split option when selected dataset has predefined splits', async () => {
    vi.spyOn(wsiApi, 'fetchDatasets').mockResolvedValue({
      items: [
        {
          dataset_id: 'ds-1',
          dataset_name: 'Dataset With Splits',
          user_id: 'u1',
          file_count: 100,
          total_size: 0,
          data_type: 'patch',
          task_type: 'patch_classification',
          aggregation_level: 'file',
          has_predefined_splits: true,
          predefined_split_counts: { train: 70, val: 15, test: 15 },
        },
      ],
      total: 1,
    })

    renderTaskConfigCard({
      config: {
        task_name: 'Test',
        task_type: 'patch_classification',
        data_type: 'patch',
        dataset_id: 'ds-1',
      },
    })

    await waitFor(() => {
      expect(screen.getByText('training.dataSplit.customSplit')).toBeInTheDocument()
    })

    expect(screen.queryByText('training.dataSplit.uploadSplits')).not.toBeInTheDocument()
    expect(screen.getByText('training.dataSplit.train:70')).toBeInTheDocument()
    expect(screen.getByText('training.dataSplit.val:15')).toBeInTheDocument()
    expect(screen.getByText('training.dataSplit.test:15')).toBeInTheDocument()
  })

  it('navigates to /register with datasetId and datasetName when upload prompt is clicked', async () => {
    vi.spyOn(wsiApi, 'fetchDatasets').mockResolvedValue({
      items: [
        {
          dataset_id: 'ds-2',
          dataset_name: 'Dataset Without Splits',
          user_id: 'u1',
          file_count: 50,
          total_size: 0,
          data_type: 'patch',
          task_type: 'patch_classification',
          aggregation_level: 'file',
          has_predefined_splits: false,
          predefined_split_counts: { train: 0, val: 0, test: 0 },
        },
      ],
      total: 1,
    })

    renderTaskConfigCard({
      config: {
        task_name: 'Test',
        task_type: 'patch_classification',
        data_type: 'patch',
        dataset_id: 'ds-2',
      },
    })

    await waitFor(() => {
      expect(screen.getByText('training.dataSplit.uploadSplits')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('training.dataSplit.uploadSplits'))

    await waitFor(() => {
      const probe = screen.getByTestId('location-probe')
      expect(probe).toHaveAttribute('data-pathname', '/register')
      expect(probe).toHaveAttribute(
        'data-state',
        JSON.stringify({ datasetId: 'ds-2', datasetName: 'Dataset Without Splits' }),
      )
    })
  })
})
