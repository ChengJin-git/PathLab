import { describe, expect, it } from 'vitest'
import { formatAutoResearchElapsed } from '@renderer/lib/autoresearchTime'

const unit = (locale: string, value: number, unit: string) => new Intl.NumberFormat(locale, { style: 'unit', unit, unitDisplay: 'short' }).format(value)

describe('research elapsed time', () => {
  it('uses hours for long research instead of hundreds of minutes', () => {
    const locale = 'zh-CN'
    expect(formatAutoResearchElapsed(0, 38652 * 1000, locale)).toBe(`${unit(locale, 10, 'hour')} ${unit(locale, 44, 'minute')}`)
  })
  it('switches to days and preserves stopped-task timestamps', () => {
    expect(formatAutoResearchElapsed(0, 183 * 3600 * 1000, 'en-US')).toBe('7 days 15 hr')
    expect(formatAutoResearchElapsed(0, 90000, 'en-US')).toBe('1 min 30 sec')
    expect(formatAutoResearchElapsed()).toBe('')
    expect(formatAutoResearchElapsed(1000, 0, 'en-US')).toBe('0 sec')
  })
})
