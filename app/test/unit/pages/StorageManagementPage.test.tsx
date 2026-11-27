import { describe, it, expect } from 'vitest'
import enUS from '../../../src/renderer/src/locales/en-US.json'
import zhCN from '../../../src/renderer/src/locales/zh-CN.json'
import zhHK from '../../../src/renderer/src/locales/zh-HK.json'

describe('Storage inventory translations', () => {
  it.each([enUS, zhCN, zhHK])('covers each file category, reference state and cleanup explanation', data => {
    const text = data.settings.storageInventory
    for (const key of ['features','patching','images','results','training','models','research','metadata','documents','system'] as const) {
      expect(text.categories[key]).toBeTruthy()
    }
    for (const key of ['orphaned','cached','referenced','recent','managed'] as const) {
      expect(text.states[key]).toBeTruthy()
      expect(text.hints[key]).toBeTruthy()
    }
    expect(text.cacheConfirm).toBeTruthy()
    expect(text.taskDeleteDescription).toBeTruthy()
    for (const key of ['selectPage', 'selectAll', 'selectionMenu', 'clearSelection', 'selectionScope', 'confirmAll', 'confirmSelected'] as const) {
      expect(text[key]).toBeTruthy()
    }
  })
})
