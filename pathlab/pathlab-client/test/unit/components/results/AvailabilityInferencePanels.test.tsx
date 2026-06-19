import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { BatchInferencePanel } from '@renderer/components/results/BatchInferencePanel'
import { IndependentInferencePanel } from '@renderer/components/results/IndependentInferencePanel'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('@renderer/contexts/BackgroundTaskContext', () => ({
  useBackgroundTask: () => ({ openPanel: vi.fn() }),
}))

vi.mock('@renderer/contexts/ToastContext', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn() }),
}))

vi.mock('@renderer/lib/trainingSubmissionTracker', () => ({
  markTrainingSubmissionPending: vi.fn(),
}))

vi.mock('@renderer/api/batchInference', () => ({
  exportBatchInferenceCsv: vi.fn(),
  fetchDatasetsForInference: vi.fn(),
  fetchWSIForIndependentInference: vi.fn(),
  getBatchInferenceResults: vi.fn(),
  getIndependentInferenceResults: vi.fn(),
  listBatchInferenceTasks: vi.fn(),
  listIndependentInferenceTasks: vi.fn(),
  startBatchInference: vi.fn(),
  startIndependentInference: vi.fn(),
}))

import {
  fetchDatasetsForInference,
  fetchWSIForIndependentInference,
  listBatchInferenceTasks,
  listIndependentInferenceTasks,
} from '@renderer/api/batchInference'

const mockFetchDatasetsForInference = vi.mocked(fetchDatasetsForInference)
const mockFetchWSIForIndependentInference = vi.mocked(fetchWSIForIndependentInference)
const mockListBatchInferenceTasks = vi.mocked(listBatchInferenceTasks)
const mockListIndependentInferenceTasks = vi.mocked(listIndependentInferenceTasks)

const trainedModel = {
  model_id: 'model-1',
  task_id: 'task-1',
  model_name: 'Classifier',
  model_path: '/models/classifier.pt',
  classes: ['tumor'],
  is_default: true,
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  task_name: 'Classifier task',
  task_type: 'wsi_classification',
}

function renderWithProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  })

  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
    </MemoryRouter>
  )
}

describe('availability-aware inference panels', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockListBatchInferenceTasks.mockResolvedValue({ items: [], total: 0 })
    mockListIndependentInferenceTasks.mockResolvedValue({ items: [], total: 0 })
  })

  it('disables cached-unavailable external datasets in batch inference', async () => {
    mockFetchDatasetsForInference.mockResolvedValue({
      items: [
        {
          dataset_id: 'ds-external-missing',
          name: 'Missing NAS dataset',
          data_type: 'wsi',
          task_type: 'wsi_classification',
          aggregation_level: 'file',
          slide_count: 3,
          availability: { status: 'unavailable', reason: 'NAS offline' },
        },
      ],
      total: 1,
    })

    renderWithProviders(<BatchInferencePanel trainedModels={[trainedModel]} />)

    await userEvent.click(screen.getByRole('button', { name: 'resultsPage.batchInference.selectModelPlaceholder' }))
    await userEvent.click(await screen.findByRole('button', { name: /Classifier task/i }))
    await userEvent.click(screen.getByRole('button', { name: 'resultsPage.batchInference.selectDatasetPlaceholder' }))

    const datasetOption = await screen.findByRole('button', { name: /Missing NAS dataset/i })
    expect(datasetOption).toBeDisabled()
    expect(screen.getByText('resultsPage.batchInference.unavailableDataset')).toBeInTheDocument()
  })

  it('disables cached-unavailable external slides in independent inference', async () => {
    mockFetchWSIForIndependentInference.mockResolvedValue({
      items: [
        {
          wsi_id: 'wsi-external-missing',
          original_filename: 'missing-slide.svs',
          dataset_id: 'ds-external-missing',
          dataset_name: 'Missing NAS dataset',
          case_id: 'case-1',
          data_type: 'wsi',
          task_type: 'wsi_classification',
          aggregation_level: 'file',
          created_at: '2026-01-01T00:00:00Z',
          availability: { status: 'unavailable', reason: 'NAS offline' },
        },
      ],
      total: 1,
      models_available: true,
    })

    renderWithProviders(<IndependentInferencePanel trainedModels={[trainedModel]} />)

    await userEvent.click(screen.getByRole('button', { name: /select model/i }))
    await userEvent.click(await screen.findByRole('button', { name: /Classifier task/i }))

    const slideOption = await screen.findByRole('button', { name: /missing-slide\.svs/i })
    expect(slideOption).toBeDisabled()
    expect(screen.getByText('resultsPage.independentInference.unavailable')).toBeInTheDocument()
  })
})
