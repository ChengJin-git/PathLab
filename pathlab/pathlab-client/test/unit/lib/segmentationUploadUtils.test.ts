import { describe, it, expect } from 'vitest'
import {
  getSegmentationStem,
  mergeSegmentationJsonFiles,
  summarizeSegmentationMatches,
} from '@renderer/lib/segmentationUploadUtils'

// ---------------------------------------------------------------------------
// getSegmentationStem
// ---------------------------------------------------------------------------

describe('getSegmentationStem', () => {
  it('strips .json extension and lowercases', () => {
    expect(getSegmentationStem('slide_001.json')).toBe('slide_001')
  })

  it('strips any non-json file extension', () => {
    expect(getSegmentationStem('slide_001.svs')).toBe('slide_001')
  })

  it('strips .json then any remaining extension (e.g. slide.ndpi.json)', () => {
    expect(getSegmentationStem('slide.ndpi.json')).toBe('slide')
  })

  it('lowercases the stem', () => {
    expect(getSegmentationStem('SLIDE_A.SVS')).toBe('slide_a')
    expect(getSegmentationStem('TUMOR_001.json')).toBe('tumor_001')
  })

  it('handles name with no extension', () => {
    expect(getSegmentationStem('slide_no_ext')).toBe('slide_no_ext')
  })

  it('handles dots in filename stem (preserves middle dots after stripping extensions)', () => {
    const stem = getSegmentationStem('my.slide.001.svs')
    expect(stem).toBe('my.slide.001')
  })
})

// ---------------------------------------------------------------------------
// mergeSegmentationJsonFiles
// ---------------------------------------------------------------------------

function makeFile(name: string): File {
  return new File(['{}'], name, { type: 'application/json' })
}

describe('mergeSegmentationJsonFiles', () => {
  it('adds new JSON files to an empty map', () => {
    const files = [makeFile('slide_001.json'), makeFile('slide_002.json')]
    const { jsonFilesByStem, duplicateJsonStems } = mergeSegmentationJsonFiles(new Map(), files)
    expect(jsonFilesByStem.size).toBe(2)
    expect(jsonFilesByStem.has('slide_001')).toBe(true)
    expect(jsonFilesByStem.has('slide_002')).toBe(true)
    expect(duplicateJsonStems).toHaveLength(0)
  })

  it('preserves existing entries that do not conflict', () => {
    const existing = new Map<string, File>([['slide_001', makeFile('slide_001.json')]])
    const { jsonFilesByStem } = mergeSegmentationJsonFiles(existing, [makeFile('slide_002.json')])
    expect(jsonFilesByStem.size).toBe(2)
  })

  it('reports duplicate when a new file has the same stem as an existing entry', () => {
    const existing = new Map<string, File>([['slide_001', makeFile('slide_001.json')]])
    const { jsonFilesByStem, duplicateJsonStems } = mergeSegmentationJsonFiles(
      existing,
      [makeFile('slide_001.json')]
    )
    expect(duplicateJsonStems).toContain('slide_001')
    expect(jsonFilesByStem.size).toBe(1)
  })

  it('reports duplicates when two new files share the same stem', () => {
    const { duplicateJsonStems } = mergeSegmentationJsonFiles(new Map(), [
      makeFile('dup.json'),
      makeFile('dup.json'),
    ])
    expect(duplicateJsonStems).toContain('dup')
  })

  it('returns duplicates sorted alphabetically', () => {
    const { duplicateJsonStems } = mergeSegmentationJsonFiles(new Map(), [
      makeFile('z.json'), makeFile('z.json'),
      makeFile('a.json'), makeFile('a.json'),
    ])
    expect(duplicateJsonStems).toEqual(['a', 'z'])
  })

  it('does not mutate the original existing map', () => {
    const existing = new Map<string, File>()
    mergeSegmentationJsonFiles(existing, [makeFile('slide_001.json')])
    expect(existing.size).toBe(0)
  })
})

// ---------------------------------------------------------------------------
// summarizeSegmentationMatches
// ---------------------------------------------------------------------------

interface FakeItem { name: string }

describe('summarizeSegmentationMatches', () => {
  it('returns all matched when every image has a corresponding JSON', () => {
    const items: FakeItem[] = [{ name: 'slide_001.svs' }, { name: 'slide_002.svs' }]
    const jsonMap = new Map([
      ['slide_001', makeFile('slide_001.json')],
      ['slide_002', makeFile('slide_002.json')],
    ])
    const result = summarizeSegmentationMatches(items, jsonMap)
    expect(result.matchedStems.size).toBe(2)
    expect(result.missingImageStems).toHaveLength(0)
    expect(result.orphanJsonStems).toHaveLength(0)
    expect(result.duplicateImageStems).toHaveLength(0)
  })

  it('identifies missing JSON (image with no JSON)', () => {
    const items: FakeItem[] = [{ name: 'slide_001.svs' }]
    const jsonMap = new Map<string, File>()
    const result = summarizeSegmentationMatches(items, jsonMap)
    expect(result.missingImageStems).toContain('slide_001')
    expect(result.matchedStems.size).toBe(0)
  })

  it('identifies orphan JSON (JSON with no matching image)', () => {
    const items: FakeItem[] = []
    const jsonMap = new Map([['orphan', makeFile('orphan.json')]])
    const result = summarizeSegmentationMatches(items, jsonMap)
    expect(result.orphanJsonStems).toContain('orphan')
    expect(result.matchedStems.size).toBe(0)
  })

  it('identifies duplicate image stems', () => {
    const items: FakeItem[] = [{ name: 'slide_001.svs' }, { name: 'slide_001.svs' }]
    const jsonMap = new Map([['slide_001', makeFile('slide_001.json')]])
    const result = summarizeSegmentationMatches(items, jsonMap)
    expect(result.duplicateImageStems).toContain('slide_001')
  })

  it('handles empty inputs gracefully', () => {
    const result = summarizeSegmentationMatches([], new Map())
    expect(result.matchedStems.size).toBe(0)
    expect(result.missingImageStems).toHaveLength(0)
    expect(result.orphanJsonStems).toHaveLength(0)
    expect(result.duplicateImageStems).toHaveLength(0)
  })

  it('returns sorted missing and orphan arrays', () => {
    const items: FakeItem[] = [{ name: 'z.svs' }, { name: 'a.svs' }]
    const jsonMap = new Map([
      ['orphan_z', makeFile('orphan_z.json')],
      ['orphan_a', makeFile('orphan_a.json')],
    ])
    const result = summarizeSegmentationMatches(items, jsonMap)
    expect(result.missingImageStems).toEqual(['a', 'z'])
    expect(result.orphanJsonStems).toEqual(['orphan_a', 'orphan_z'])
  })
})
