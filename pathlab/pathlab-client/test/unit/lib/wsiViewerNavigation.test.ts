import { describe, expect, it } from 'vitest'
import {
  buildSlideNavigationTooltip,
  getAdjacentSlideIds,
  shouldPersistAnnotationsBeforeSlideNavigation,
} from '../../../src/renderer/src/lib/wsiViewerNavigation'

describe('wsiViewerNavigation', () => {
  it('uses slide-specific labels for previous and next navigation', () => {
    expect(
      buildSlideNavigationTooltip({
        direction: 'previous',
        hasTarget: true,
        shortcut: 'Q',
        labels: {
          previousSlide: '上一张',
          nextSlide: '下一张',
          noPreviousSlide: '没有上一张切片',
          noNextSlide: '没有下一张切片',
        },
      })
    ).toBe('上一张 (Q)')

    expect(
      buildSlideNavigationTooltip({
        direction: 'next',
        hasTarget: true,
        shortcut: 'E',
        labels: {
          previousSlide: '上一张',
          nextSlide: '下一张',
          noPreviousSlide: '没有上一张切片',
          noNextSlide: '没有下一张切片',
        },
      })
    ).toBe('下一张 (E)')

    expect(
      buildSlideNavigationTooltip({
        direction: 'previous',
        hasTarget: false,
        shortcut: 'Q',
        labels: {
          previousSlide: '上一张',
          nextSlide: '下一张',
          noPreviousSlide: '没有上一张切片',
          noNextSlide: '没有下一张切片',
        },
      })
    ).toBe('没有上一张切片')
  })

  it('only persists annotations before navigation when annotation mode is active', () => {
    expect(shouldPersistAnnotationsBeforeSlideNavigation(false, true)).toBe(false)
    expect(shouldPersistAnnotationsBeforeSlideNavigation(true, false)).toBe(false)
    expect(shouldPersistAnnotationsBeforeSlideNavigation(true, true)).toBe(true)
  })

  it('derives previous and next slide ids from an ordered id list', () => {
    expect(getAdjacentSlideIds(['wsi-1', 'wsi-2', 'wsi-3'], 'wsi-2')).toEqual({
      previousId: 'wsi-1',
      nextId: 'wsi-3',
    })

    expect(getAdjacentSlideIds(['wsi-1', 'wsi-2', 'wsi-3'], 'wsi-1')).toEqual({
      previousId: null,
      nextId: 'wsi-2',
    })

    expect(getAdjacentSlideIds(['wsi-1', 'wsi-2', 'wsi-3'], 'wsi-3')).toEqual({
      previousId: 'wsi-2',
      nextId: null,
    })

    expect(getAdjacentSlideIds(['wsi-1', 'wsi-2', 'wsi-3'], 'missing')).toEqual({
      previousId: null,
      nextId: null,
    })
  })
})
