import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ok, errResp } from '../../helpers/apiHelpers'

vi.mock('@renderer/config', () => ({
  API_BASE: 'http://localhost:6100',
  updateApiBase: vi.fn(),
  initializeApiConfig: vi.fn(),
}))

import {
  fetchTrainingOptions,
  type TrainingOptionsResponse,
} from '@renderer/api/trainingOptions'
import { setAuthToken } from '@renderer/api/client'

const mockFetch = vi.mocked(fetch)


const MOCK_OPTIONS: TrainingOptionsResponse = {
  feature_extractors: [
    { id: 'resnet50', name: 'ResNet50', description: 'ImageNet pretrained CNN', supports_spatial: false },
    { id: 'uni', name: 'UNI', description: 'DINOv2 ViT-L/16', supports_spatial: true },
  ],
  aggregators: [
    { id: 'abmil', name: 'ABMIL', description: 'Attention-based MIL', detail: 'Learns importance weights' },
    { id: 'meanmil', name: 'MeanMIL', description: 'Simple average pooling', detail: 'Average of all patch features' },
  ],
  segmentation_architectures: [
    { id: 'unet', name: 'U-Net', description: 'Classic encoder-decoder' },
  ],
  segmentation_backbones: [
    { id: 'resnet50', name: 'ResNet-50', description: '23M params', group: 'ResNet' },
  ],
  segmentation_losses: [
    { id: 'DiceLoss', name: 'Dice Loss', description: 'Overlap-based' },
  ],
  optimizers: [
    { value: 'adam', label: 'Adam' },
    { value: 'sgd', label: 'SGD' },
  ],
}

beforeEach(() => {
  setAuthToken('test_token')
})

describe('fetchTrainingOptions', () => {
  it('fetches from GET /training/options', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_OPTIONS))
    await fetchTrainingOptions()
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('/training/options')
    expect(String(url)).toMatch(/^http:\/\/localhost:6100/)
  })

  it('returns the full options response', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_OPTIONS))
    const result = await fetchTrainingOptions()
    expect(result.feature_extractors).toHaveLength(2)
    expect(result.feature_extractors[0].id).toBe('resnet50')
    expect(result.aggregators).toHaveLength(2)
    expect(result.aggregators[0].id).toBe('abmil')
    expect(result.segmentation_architectures).toHaveLength(1)
    expect(result.segmentation_backbones).toHaveLength(1)
    expect(result.segmentation_losses).toHaveLength(1)
    expect(result.optimizers).toHaveLength(2)
  })

  it('caches results and does not fetch twice within TTL', async () => {
    mockFetch.mockResolvedValue(ok(MOCK_OPTIONS))
    await fetchTrainingOptions()
    await fetchTrainingOptions()
    expect(mockFetch).toHaveBeenCalledOnce()
  })

  it('forceRefresh=true bypasses the cache', async () => {
    mockFetch.mockResolvedValue(ok(MOCK_OPTIONS))
    await fetchTrainingOptions()
    await fetchTrainingOptions(true)
    expect(mockFetch).toHaveBeenCalledTimes(2)
  })

  it('throws on API error', async () => {
    mockFetch.mockResolvedValueOnce(errResp({ detail: 'Unauthorized' }, 401))
    await expect(fetchTrainingOptions()).rejects.toThrow()
  })
})
