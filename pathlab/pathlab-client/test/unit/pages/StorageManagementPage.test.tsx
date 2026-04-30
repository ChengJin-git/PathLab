import { describe, it, expect } from 'vitest'
import enUS from '../../../src/renderer/src/locales/en-US.json'
import zhCN from '../../../src/renderer/src/locales/zh-CN.json'
import zhHK from '../../../src/renderer/src/locales/zh-HK.json'

const LOCALES = [
  { name: 'en-US', data: enUS },
  { name: 'zh-CN', data: zhCN },
  { name: 'zh-HK', data: zhHK },
]

describe('StorageManagementPage i18n completeness', () => {
  it('has ai_result_bundles in storagePage.categories for all locales', () => {
    for (const { name, data } of LOCALES) {
      expect(
        (data as any).storagePage?.categories?.ai_result_bundles,
        `Missing ai_result_bundles in ${name} storagePage.categories`
      ).toBeDefined()
    }
  })

  it('has ai_result_bundles in storagePage.orphanedCategories for all locales', () => {
    for (const { name, data } of LOCALES) {
      expect(
        (data as any).storagePage?.orphanedCategories?.ai_result_bundles,
        `Missing ai_result_bundles in ${name} storagePage.orphanedCategories`
      ).toBeDefined()
    }
  })
})
