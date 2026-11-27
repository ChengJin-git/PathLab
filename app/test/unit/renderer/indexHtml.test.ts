import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { resolve } from 'path'

describe('index.html startup scripts', () => {
  const indexPath = resolve(__dirname, '../../../src/renderer/index.html')
  const html = readFileSync(indexPath, 'utf-8')

  it('should not contain parser-blocking external <script src="https://..."> before the app entry script', () => {
    const scriptSrcRegex = /<script[^>]*src="([^"]*)"[^>]*>/gi
    const matches = Array.from(html.matchAll(scriptSrcRegex))

    const mainEntryIndex = html.search(/<script[^>]*src="[^"]*main\.(tsx|js)"[^>]*>/i)
    expect(mainEntryIndex).toBeGreaterThan(-1)

    for (const match of matches) {
      const scriptIndex = match.index ?? 0
      if (scriptIndex >= mainEntryIndex) continue

      const src = match[1]
      const fullTag = match[0]

      if (src.startsWith('https://') || src.startsWith('http://')) {
        const isAsync = fullTag.includes('async')
        const isDefer = fullTag.includes('defer')
        expect(
          isAsync || isDefer,
          `Found parser-blocking external script before main entry: ${src}\nTag: ${fullTag}`
        ).toBe(true)
      }
    }
  })

  it('should not contain any OpenSeadragon CDN script', () => {
    expect(html).not.toMatch(/cdnjs\.cloudflare\.com.*openseadragon/i)
    expect(html).not.toMatch(/openseadragon.*cdnjs/i)
  })

})
