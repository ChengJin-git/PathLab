import { describe, expect, it } from 'vitest'
import enUS from '../../../src/renderer/src/locales/en-US.json'
import zhCN from '../../../src/renderer/src/locales/zh-CN.json'
import zhHK from '../../../src/renderer/src/locales/zh-HK.json'

describe('backgroundTask.typeLabels.autoresearch i18n coverage', () => {
  it('en-US locale has backgroundTask.typeLabels.autoresearch', () => {
    expect(enUS.backgroundTask.typeLabels.autoresearch).toBeDefined()
  })

  it('zh-CN locale has backgroundTask.typeLabels.autoresearch', () => {
    expect(zhCN.backgroundTask.typeLabels.autoresearch).toBeDefined()
  })

  it('zh-HK locale has backgroundTask.typeLabels.autoresearch', () => {
    expect(zhHK.backgroundTask.typeLabels.autoresearch).toBeDefined()
  })
})
