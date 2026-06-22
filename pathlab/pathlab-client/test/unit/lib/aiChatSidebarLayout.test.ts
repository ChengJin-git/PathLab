import { describe, expect, it } from 'vitest'

import { getSidebarToggleBarClassName } from '@renderer/lib/aiChatSidebarLayout'

describe('getSidebarToggleBarClassName', () => {
  it('keeps a stable left-aligned layout when expanded and collapsed', () => {
    const expanded = getSidebarToggleBarClassName(true)
    const collapsed = getSidebarToggleBarClassName(false)

    expect(expanded).toContain('items-center')
    expect(collapsed).toContain('items-center')
    expect(expanded).toContain('justify-start')
    expect(collapsed).toContain('justify-start')
    expect(expanded).not.toContain('flex-col')
    expect(collapsed).not.toContain('flex-col')
  })
})
