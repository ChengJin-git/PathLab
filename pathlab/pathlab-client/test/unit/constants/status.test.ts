import { describe, expect, it } from 'vitest'
import {
  getTrainingStatusLabel,
  TRAINING_STATUS_LABELS,
  TASK_DETAIL_STATUS_BADGES,
  TASK_LIST_STATUS_BADGES,
} from '@renderer/constants/status'
import enUS from '@renderer/locales/en-US.json'
import zhCN from '@renderer/locales/zh-CN.json'
import zhHK from '@renderer/locales/zh-HK.json'

describe('training status label semantics', () => {
  it('training.pending means dataset integrity checking', () => {
    expect(getTrainingStatusLabel('pending')).toBe('Checking Dataset Integrity')
  })

  it('training.queued continues to mean queue waiting', () => {
    expect(getTrainingStatusLabel('queued')).toBe('Queued')
  })

  it('exports training status labels with updated pending wording', () => {
    expect(TRAINING_STATUS_LABELS['pending']).toBe('Checking Dataset Integrity')
    expect(TRAINING_STATUS_LABELS['queued']).toBe('Queued')
  })

  it('TASK_DETAIL_STATUS_BADGES reflect updated pending wording', () => {
    expect(TASK_DETAIL_STATUS_BADGES['pending'].label).toBe('Checking Dataset Integrity')
    expect(TASK_DETAIL_STATUS_BADGES['queued'].label).toBe('Queued')
  })

  it('TASK_LIST_STATUS_BADGES reflect updated pending wording', () => {
    expect(TASK_LIST_STATUS_BADGES['pending'].label).toBe('Checking Dataset Integrity')
    expect(TASK_LIST_STATUS_BADGES['queued'].label).toBe('Queued')
  })

  it('localizes training.pending without changing training.queued semantics', () => {
    expect(zhCN.backgroundTask.serverStatus.training.pending).toBe('检查数据集完整性')
    expect(zhCN.backgroundTask.serverStatus.training.queued).toBe('排队中')
    expect(zhHK.backgroundTask.serverStatus.training.pending).toBe('檢查資料集完整性')
    expect(zhHK.backgroundTask.serverStatus.training.queued).toBe('排隊中')
    expect(enUS.backgroundTask.serverStatus.training.pending).toBe('Checking Dataset Integrity')
    expect(enUS.backgroundTask.serverStatus.training.queued).toBe('Queued')
  })
})
