import { describe, expect, it } from 'vitest'
import { parseTaskConfig } from '@renderer/components/chat/TaskConfigCard'

describe('parseTaskConfig', () => {
  it('normalizes legacy segmentation chat configs to the canonical patch segmentation task', () => {
    const parsed = parseTaskConfig(`
      [TASK_CONFIG]
      {"task_name":"Segment","task_type":"segmentation","data_type":"wsi","seg_loss_names":["DiceLoss"]}
      [/TASK_CONFIG]
    `)

    expect(parsed?.task_type).toBe('patch_segmentation')
    expect(parsed?.data_type).toBe('patch')
  })

  it('normalizes legacy classification chat configs using the declared data type', () => {
    const parsed = parseTaskConfig(`
      [TASK_CONFIG]
      {"task_name":"Classify patches","task_type":"classification","data_type":"patch"}
      [/TASK_CONFIG]
    `)

    expect(parsed?.task_type).toBe('patch_classification')
    expect(parsed?.data_type).toBe('patch')
  })

  it('normalizes legacy survival chat configs to WSI survival', () => {
    const parsed = parseTaskConfig(`
      [TASK_CONFIG]
      {"task_name":"Survival","task_type":"survival","data_type":"patch"}
      [/TASK_CONFIG]
    `)

    expect(parsed?.task_type).toBe('wsi_survival')
    expect(parsed?.data_type).toBe('wsi')
  })
})
