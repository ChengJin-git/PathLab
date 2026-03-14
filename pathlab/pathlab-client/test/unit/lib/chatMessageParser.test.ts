import { describe, it, expect } from 'vitest'
import {
  sanitizeConfigBlocksForAI,
  isPdfContextMessage,
} from '@renderer/lib/chatMessageParser'

describe('sanitizeConfigBlocksForAI', () => {
  it('removes [CITATION_CONTEXTS] blocks', () => {
    const input = 'before\n[CITATION_CONTEXTS]some citations[/CITATION_CONTEXTS]\nafter'
    expect(sanitizeConfigBlocksForAI(input)).toBe('before\n\nafter')
  })

  it('removes [OPTIONS] blocks', () => {
    const input = 'before\n[OPTIONS]option1\noption2[/OPTIONS]\nafter'
    expect(sanitizeConfigBlocksForAI(input)).toBe('before\n\nafter')
  })

  it('removes [MODEL_LIST] blocks', () => {
    const input = 'before\n[MODEL_LIST]{"models": []}[/MODEL_LIST]\nafter'
    expect(sanitizeConfigBlocksForAI(input)).toBe('before\n\nafter')
  })

  it('removes [PATCH_INFERENCE] blocks', () => {
    const input = '[PATCH_INFERENCE]data[/PATCH_INFERENCE]'
    expect(sanitizeConfigBlocksForAI(input)).toBe('')
  })

  it('strips submitted_task_id from TASK_CONFIG blocks', () => {
    const config = JSON.stringify({ task_type: 'train', submitted_task_id: 'tid_123' }, null, 2)
    const input = `[TASK_CONFIG]\n${config}\n[/TASK_CONFIG]`
    const result = sanitizeConfigBlocksForAI(input)
    expect(result).toContain('[TASK_CONFIG]')
    expect(result).not.toContain('submitted_task_id')
    expect(result).toContain('task_type')
  })

  it('strips submitted_analysis_id and external_validation_task_id from ANALYSIS_CONFIG', () => {
    const config = JSON.stringify({
      analysis_type: 'inference',
      submitted_analysis_id: 'aid_456',
      external_validation_task_id: 'evid_789',
    }, null, 2)
    const input = `[ANALYSIS_CONFIG]\n${config}\n[/ANALYSIS_CONFIG]`
    const result = sanitizeConfigBlocksForAI(input)
    expect(result).not.toContain('submitted_analysis_id')
    expect(result).not.toContain('external_validation_task_id')
    expect(result).toContain('analysis_type')
  })

  it('strips persistence fields from DATASET_REGISTRATION blocks', () => {
    const config = JSON.stringify({
      dataset_name: 'TCGA',
      submitted_task_id: 'x',
      submitted_file_count: 5,
      submitted_dataset_name: 'old',
      submitted_mode: 'upload',
    }, null, 2)
    const input = `[DATASET_REGISTRATION]\n${config}\n[/DATASET_REGISTRATION]`
    const result = sanitizeConfigBlocksForAI(input)
    expect(result).toContain('dataset_name')
    expect(result).not.toContain('submitted_task_id')
    expect(result).not.toContain('submitted_file_count')
    expect(result).not.toContain('submitted_dataset_name')
    expect(result).not.toContain('submitted_mode')
  })

  it('leaves blocks with no persistence fields unchanged', () => {
    const config = JSON.stringify({ task_type: 'inference' }, null, 2)
    const input = `[TASK_CONFIG]\n${config}\n[/TASK_CONFIG]`
    const result = sanitizeConfigBlocksForAI(input)
    expect(result).toBe(input)
  })

  it('handles malformed JSON inside config blocks gracefully', () => {
    const input = '[TASK_CONFIG]\nnot-json\n[/TASK_CONFIG]'
    expect(() => sanitizeConfigBlocksForAI(input)).not.toThrow()
    expect(sanitizeConfigBlocksForAI(input)).toBe('[TASK_CONFIG]\nnot-json\n[/TASK_CONFIG]')
  })

  it('returns empty string for empty input', () => {
    expect(sanitizeConfigBlocksForAI('')).toBe('')
  })

  it('passes through plain text unchanged', () => {
    const text = 'This is a regular message without any special blocks.'
    expect(sanitizeConfigBlocksForAI(text)).toBe(text)
  })
})

describe('isPdfContextMessage', () => {
  it('returns true for valid PDF context message', () => {
    expect(isPdfContextMessage('[PDF_CONTEXT]some content[/PDF_CONTEXT]')).toBe(true)
  })

  it('returns true for multiline PDF context', () => {
    const msg = '[PDF_CONTEXT]\npage 1 content\npage 2 content\n[/PDF_CONTEXT]'
    expect(isPdfContextMessage(msg)).toBe(true)
  })

  it('returns false for plain text', () => {
    expect(isPdfContextMessage('hello world')).toBe(false)
  })

  it('returns false when only starts with tag', () => {
    expect(isPdfContextMessage('[PDF_CONTEXT]content without closing tag')).toBe(false)
  })

  it('returns false when only ends with tag', () => {
    expect(isPdfContextMessage('content[/PDF_CONTEXT]')).toBe(false)
  })

  it('returns false for empty string', () => {
    expect(isPdfContextMessage('')).toBe(false)
  })

  it('returns false for other block types', () => {
    expect(isPdfContextMessage('[CITATION_CONTEXTS]data[/CITATION_CONTEXTS]')).toBe(false)
  })
})
