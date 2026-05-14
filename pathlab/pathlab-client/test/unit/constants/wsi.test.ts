import { describe, it, expect } from 'vitest'
import { organSources, organSourceKeyMap } from '../../../src/renderer/src/constants/wsi'
import enUS from '../../../src/renderer/src/locales/en-US.json'
import zhCN from '../../../src/renderer/src/locales/zh-CN.json'
import zhHK from '../../../src/renderer/src/locales/zh-HK.json'

describe('organSources constants', () => {
  it('contains Hematologic', () => {
    expect(organSources).toContain('Hematologic')
  })

  it('orders Hematologic after Blood Vessel and before Bone', () => {
    const bloodVesselIndex = organSources.indexOf('Blood Vessel')
    const hematologicIndex = organSources.indexOf('Hematologic')
    const boneIndex = organSources.indexOf('Bone')

    expect(bloodVesselIndex).toBeGreaterThanOrEqual(0)
    expect(hematologicIndex).toBeGreaterThanOrEqual(0)
    expect(boneIndex).toBeGreaterThanOrEqual(0)

    expect(hematologicIndex).toBeGreaterThan(bloodVesselIndex)
    expect(hematologicIndex).toBeLessThan(boneIndex)
  })

  it('maps Hematologic to hematologic in organSourceKeyMap', () => {
    expect(organSourceKeyMap['Hematologic']).toBe('hematologic')
  })
})

describe('organSources i18n labels', () => {
  it('en-US includes organSources.hematologic as Hematologic', () => {
    expect(enUS.organSources.hematologic).toBe('Hematologic')
  })

  it('zh-CN includes organSources.hematologic as 血液', () => {
    expect(zhCN.organSources.hematologic).toBe('血液')
  })

  it('zh-HK includes organSources.hematologic as 血液', () => {
    expect(zhHK.organSources.hematologic).toBe('血液')
  })
})
