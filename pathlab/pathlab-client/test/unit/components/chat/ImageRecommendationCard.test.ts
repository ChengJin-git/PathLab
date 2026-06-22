import { describe, expect, it } from 'vitest'
import type { WSISummary } from '@renderer/api'
import {
  rankImagesByQuery,
  shouldUseQueryRanking,
} from '@renderer/components/chat/ImageRecommendationCard'

describe('rankImagesByQuery', () => {
  const makeImages = (names: string[]): WSISummary[] =>
    names.map((name, i) => ({
      wsi_id: `wsi-${i}`,
      original_filename: name,
      dataset_id: null,
      dataset_name: null,
      case_id: null,
      label: null,
      file_extension: name.includes('.') ? name.slice(name.lastIndexOf('.')) : '',
      age: null,
      gender: null,
      source: null,
      event_time: null,
      event_status: null,
      split: null,
      file_size: null,
      data_type: 'wsi',
      created_at: null,
    }))

  it('returns images unmodified for empty query', () => {
    const images = makeImages(['a.svs', 'b.svs'])
    expect(rankImagesByQuery(images, '')).toEqual(images)
    expect(rankImagesByQuery(images, '   ')).toEqual(images)
  })

  it('exact full filename match wins over unrelated images', () => {
    const images = makeImages(['target.svs', 'other.svs', 'another.svs'])
    const ranked = rankImagesByQuery(images, 'target.svs')
    expect(ranked[0].original_filename).toBe('target.svs')
  })

  it('exact basename match wins when query omits extension', () => {
    const images = makeImages(['target.svs', 'target_patch.svs', 'other.svs'])
    const ranked = rankImagesByQuery(images, 'target')
    expect(ranked[0].original_filename).toBe('target.svs')
    // target_patch should still rank above unrelated
    expect(ranked[1].original_filename).toBe('target_patch.svs')
  })

  it('fuzzy noisy query still points to the right file', () => {
    const images = makeImages(['TCGA-02-0001.svs', 'TCGA-02-0002.svs', 'random.svs'])
    const ranked = rankImagesByQuery(images, 'tcga 02 0001')
    expect(ranked[0].original_filename).toBe('TCGA-02-0001.svs')
  })

  it('prefix match ranks above substring match', () => {
    const images = makeImages(['prefix_match.svs', 'not_prefix_match.svs', 'unrelated.svs'])
    const ranked = rankImagesByQuery(images, 'prefix')
    expect(ranked[0].original_filename).toBe('prefix_match.svs')
    expect(ranked[1].original_filename).toBe('not_prefix_match.svs')
  })

  it('all words present heuristic ranks above unrelated', () => {
    const images = makeImages(['slide_A_001.svs', 'slide_B_001.svs', 'something_else.svs'])
    const ranked = rankImagesByQuery(images, 'slide a')
    expect(ranked[0].original_filename).toBe('slide_A_001.svs')
    expect(ranked[1].original_filename).toBe('slide_B_001.svs')
    expect(ranked[2].original_filename).toBe('something_else.svs')
  })

  it('preserves stable sort for equal scores', () => {
    const images = makeImages(['b.svs', 'a.svs'])
    const ranked = rankImagesByQuery(images, 'nomatch')
    expect(ranked[0].original_filename).toBe('a.svs')
    expect(ranked[1].original_filename).toBe('b.svs')
  })
})

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
