import { describe, expect, it } from 'vitest'

import { CUSTOM_MODEL_SENTINEL, MODEL_OPTIONS, MULTIMODAL_MODELS, isCustomModelId } from '@renderer/constants/models'

describe('model catalog', () => {
  it('exposes multimodal model capabilities without importing settings UI', () => {
    const multimodalIds = MODEL_OPTIONS.filter(model => model.multimodal).map(model => model.id)

    expect(MULTIMODAL_MODELS).toEqual(new Set(multimodalIds))
    expect(MULTIMODAL_MODELS.has('qwen/qwen3.6-plus:free')).toBe(true)
  })

  it('detects custom model identifiers', () => {
    expect(isCustomModelId('custom/local-model')).toBe(true)
    expect(isCustomModelId(CUSTOM_MODEL_SENTINEL)).toBe(false)
    expect(isCustomModelId('qwen/qwen3.6-plus:free')).toBe(false)
  })
})
