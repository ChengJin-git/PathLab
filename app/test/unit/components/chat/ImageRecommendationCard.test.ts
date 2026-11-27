import { describe, expect, it } from 'vitest'
import {
  shouldUseQueryRanking,
} from '@renderer/components/chat/ImageRecommendationCard'

describe('shouldUseQueryRanking', () => {
  it('returns false for empty query', () => {
    expect(shouldUseQueryRanking('')).toBe(false)
  })

  it('returns true for filename-like queries', () => {
    expect(shouldUseQueryRanking('slide1.svs')).toBe(true)
    expect(shouldUseQueryRanking('TCGA-02-0001')).toBe(true)
    expect(shouldUseQueryRanking('patch_42')).toBe(true)
  })

  it('returns false for long generic sentences', () => {
    expect(shouldUseQueryRanking('show me some interesting images from the dataset')).toBe(false)
    expect(shouldUseQueryRanking('please display a few examples of tumor patches')).toBe(false)
  })

  it('returns true for short generic queries (preserves existing behavior change minimally)', () => {
    // Short queries may still be generic, but we err on the side of ranking
    // because the cost is low and it prevents missing obvious filename matches.
    expect(shouldUseQueryRanking('tumor')).toBe(true)
    expect(shouldUseQueryRanking('benign patch')).toBe(true)
  })
})
