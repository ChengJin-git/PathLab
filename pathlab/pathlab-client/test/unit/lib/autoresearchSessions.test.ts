import { afterEach, describe, expect, it } from 'vitest'
import i18n from '@renderer/i18n'
import {
  displaySessionStatus,
  trainingProgressConsoleLabel,
  trainingProgressEpochLabel,
  sessionTrainingProgressLabel,
} from '@renderer/lib/autoresearchSessions'

describe('autoresearch training progress labels', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en-US')
  })

  it('marks quick start epoch progress distinctly', () => {
    const progress = {
      quick_check: true,
      run_kind: 'quick_check',
      current_epoch: 1,
      total_epochs: 2,
      current_val_auc: 0.9123,
      best_val_auc: 0.9456,
    }

    expect(trainingProgressEpochLabel(progress)).toBe('Quick start · Epoch 1/2')
    expect(trainingProgressConsoleLabel(progress)).toBe(
      'Quick start · Epoch 1/2 · val AUC 0.912 · best 0.946',
    )
    expect(sessionTrainingProgressLabel({
      session_id: 's-quick',
      question: 'quick run',
      status: 'running',
      current_iteration: 0,
      max_iterations: 2,
      training_progress: progress,
    })).toBe('Iter 1/2 · Quick start · Epoch 1/2 · AUC 0.912 · best 0.946')
  })

  it('omits session training progress labels after the session ends', () => {
    expect(sessionTrainingProgressLabel({
      session_id: 's-completed',
      question: 'completed run',
      status: 'completed',
      stage: 'completed',
      current_iteration: 1,
      max_iterations: 1,
      training_progress: {
        run_kind: 'training',
        current_epoch: 4,
        total_epochs: 5,
        current_val_auc: 1,
        best_val_auc: 1,
      },
    })).toBe('')
  })

  it('marks non-quick epoch progress as training', () => {
    expect(trainingProgressEpochLabel({
      quick_check: false,
      run_kind: 'training',
      current_epoch: 7,
      total_epochs: 30,
    })).toBe('Training · Epoch 7/30')
  })

  it('renders live training progress from zh-CN translations', async () => {
    await i18n.changeLanguage('zh-CN')
    const progress = {
      quick_check: true,
      run_kind: 'quick_check',
      current_epoch: 1,
      total_epochs: 2,
      current_val_auc: 0.9123,
      best_val_auc: 0.9456,
    }

    expect(trainingProgressEpochLabel(progress)).toBe('快速启动 · 第 1/2 轮训练')
    expect(trainingProgressConsoleLabel(progress)).toBe('快速启动 · 第 1/2 轮训练 · 验证 AUC 0.912 · 最佳 0.946')
    expect(sessionTrainingProgressLabel({
      session_id: 's-quick-cn',
      question: 'quick run',
      status: 'running',
      current_iteration: 0,
      max_iterations: 2,
      training_progress: progress,
    })).toBe('第 1/2 轮 · 快速启动 · 第 1/2 轮训练 · AUC 0.912 · 最佳 0.946')
  })

  it('renders finished status from zh-CN translations', async () => {
    await i18n.changeLanguage('zh-CN')

    expect(displaySessionStatus('finished')).toBe('已完成')
  })
})
