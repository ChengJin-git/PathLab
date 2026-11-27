import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { BatchInferenceConfigCard, parseBatchInferenceConfig } from '@renderer/components/chat/BatchInferenceConfigCard'
import * as batchInferenceApi from '@renderer/api/batchInference'
import { getIncompleteBlock } from '@renderer/lib/utils/chatBlockRegistry'

vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: vi.fn() },
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('react-router-dom', () => ({
  useNavigate: () => vi.fn(),
}))

describe('BatchInferenceConfigCard', () => {
  it('hides a streaming incomplete configuration until its card can be parsed', () => {
    const content = '准备预测配置。\n[BATCH_INFERENCE_CONFIG]{"model_id":"m1"'
    expect(getIncompleteBlock(content, true)).toEqual({ content: '准备预测配置。', incompleteTag: 'BATCH_INFERENCE_CONFIG' })
  })
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('parses uploaded-image batch inference configs with wsi ids', () => {
    const parsed = parseBatchInferenceConfig(`
      [BATCH_INFERENCE_CONFIG]
      {"mode":"uploaded_wsi","model_id":"model_1","wsi_ids":["wsi_1","wsi_2"],"model_name":"Classifier"}
      [/BATCH_INFERENCE_CONFIG]
    `)

    expect(parsed?.mode).toBe('uploaded_wsi')
    expect(parsed?.model_id).toBe('model_1')
    expect(parsed?.wsi_ids).toEqual(['wsi_1', 'wsi_2'])
  })

  it('submits an existing dataset inference card once on confirmation', async () => {
    const submit = vi.spyOn(batchInferenceApi, 'startBatchInference').mockResolvedValue({
      task_id: 'batch_1', status: 'queued',
    } as Awaited<ReturnType<typeof batchInferenceApi.startBatchInference>>)
    const config = { mode: 'dataset' as const, model_id: 'model_1', model_task_id: 'train_1', dataset_id: 'ds_1' }
    const view = render(<BatchInferenceConfigCard config={config} submitTrigger={2} />)
    expect(submit).not.toHaveBeenCalled()
    view.rerender(<BatchInferenceConfigCard config={config} submitTrigger={3} />)
    await waitFor(() => expect(submit).toHaveBeenCalledTimes(1))
    expect(submit).toHaveBeenCalledWith({ model_id: 'model_1', model_task_id: 'train_1', dataset_id: 'ds_1' })
    view.rerender(<BatchInferenceConfigCard config={config} submitTrigger={4} />)
    expect(submit).toHaveBeenCalledTimes(1)
  })

  it('submits uploaded-image configs through independent inference endpoint', async () => {
    const startIndependentInference = vi
      .spyOn(batchInferenceApi, 'startIndependentInference')
      .mockResolvedValue({
        task_id: 'indinfer_1',
        status: 'queued',
        message: 'queued',
        total_wsi: 2,
        model_id: 'model_1',
        model_task_id: 'task_1',
        wsi_ids: ['wsi_1', 'wsi_2'],
        skipped: [],
      })
    const startBatchInference = vi.spyOn(batchInferenceApi, 'startBatchInference')

    render(
      <BatchInferenceConfigCard
        config={{
          mode: 'uploaded_wsi',
          model_id: 'model_1',
          model_name: 'Classifier',
          wsi_ids: ['wsi_1', 'wsi_2'],
        }}
      />,
    )

    fireEvent.click(screen.getByText('chatComponents.batchInferenceConfig.submit'))

    await waitFor(() => {
      expect(startIndependentInference).toHaveBeenCalledWith({ model_id: 'model_1', wsi_ids: ['wsi_1', 'wsi_2'] })
    })
    expect(startBatchInference).not.toHaveBeenCalled()
  })
})
