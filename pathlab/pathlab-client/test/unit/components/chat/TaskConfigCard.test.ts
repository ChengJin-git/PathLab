import { describe, expect, it } from 'vitest'
import { parseTaskConfig } from '@renderer/components/chat/TaskConfigCard'

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
