import { render, screen, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ModelsTab } from '@renderer/components/settings/ModelsTab'
import { getTrainedModels } from '@renderer/api'
import i18n from '@renderer/i18n'
import { TooltipProvider } from '@renderer/components/ui/tooltip'

vi.mock('@renderer/api', () => ({ getTrainedModels: vi.fn(), updateTrainedModel: vi.fn(), deleteTrainedModel: vi.fn(), downloadTrainedModelExport: vi.fn() }))
beforeEach(async () => { await i18n.changeLanguage('en-US') })
afterEach(() => { cleanup(); vi.clearAllMocks() })

it('shows connected research models like other active models without long status prose', async () => {
  vi.mocked(getTrainedModels).mockResolvedValue({ total: 1, items: [{
    model_id: 'research_model', task_id: 'run', model_name: 'LinearSVM', classes: ['A','B'],
    model_path: 'model.joblib', is_active: true, is_default: false, created_at: '2026-10-29T00:00:00Z',
    source: 'autoresearch', research_session_id: 'session', inference_ready: true,
    val_metrics: { 'oof.auc': .833333, 'test.auc': 0 },
    metric_groups: [{ split: 'oof', metrics: { auc: .833333, accuracy: .714 } }, { split: 'test', metrics: { auc: 0, accuracy: .4 } }]
  }] })
  render(<MemoryRouter><TooltipProvider><ModelsTab showConfirmDialog={vi.fn()} closeConfirmDialog={vi.fn()} /></TooltipProvider></MemoryRouter>)
  expect((await screen.findAllByText('Active')).length).toBeGreaterThan(0)
  expect(screen.queryByText(/standard PathLab inference is not connected/)).not.toBeInTheDocument()
  expect(screen.getAllByText('oof · AUROC').length).toBeGreaterThan(0)
  expect(screen.getAllByText('0.833').length).toBeGreaterThan(0)
  expect(screen.getAllByText('0.000').length).toBeGreaterThan(0)
  expect(screen.queryByText('Inactive')).not.toBeInTheDocument()
  expect(screen.queryByText('Loss')).not.toBeInTheDocument()
})
