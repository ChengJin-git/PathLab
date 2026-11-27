import { describe, expect, it } from 'vitest'
import enUS from '@renderer/locales/en-US.json'
import zhCN from '@renderer/locales/zh-CN.json'
import zhHK from '@renderer/locales/zh-HK.json'
import i18n, { changeLanguage, i18nReady } from '@renderer/i18n'

function keys(value: unknown, prefix = ''): string[] {
  if (!value || typeof value !== 'object') return [prefix]
  return Object.entries(value).flatMap(([key, child]) => keys(child, prefix ? `${prefix}.${key}` : key))
}

describe('i18n', () => {
  it('keeps every locale on one key set, because no fallback language is loaded', () => {
    const english = keys(enUS).sort()
    expect(keys(zhCN).sort()).toEqual(english)
    expect(keys(zhHK).sort()).toEqual(english)
  })

  it('loads a language bundle on demand before switching to it', async () => {
    await i18nReady
    await changeLanguage('zh-CN')
    expect(i18n.language).toBe('zh-CN')
    expect(i18n.hasResourceBundle('zh-CN', 'translation')).toBe(true)
    expect(i18n.t('autoResearch.workbench.advancedSettings')).toBe('高级设置')
    expect(localStorage.getItem('i18nextLng')).toBe('zh-CN')
  })
})
