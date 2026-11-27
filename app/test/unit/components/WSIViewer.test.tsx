import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { readFileSync } from 'fs'
import { resolve } from 'path'
import WSIViewer from '@renderer/components/WSIViewer'
import { TooltipProvider } from '@renderer/components/ui/tooltip'

vi.mock('react-i18next', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-i18next')>()
  return {
    ...actual,
    useTranslation: () => ({ t: (key: string) => key }),
  }
})

vi.mock('@renderer/config', () => ({
  API_BASE: 'http://localhost:6100',
  PREPROCESSING_BASE: 'http://localhost:6101',
}))

vi.mock('@renderer/api/heatmap', async () => {
  const actual = await vi.importActual<typeof import('@renderer/api/heatmap')>('@renderer/api/heatmap')
  return {
    ...actual,
    getPatchFileImageUrl: vi.fn((wsiId: string) => `full://${wsiId}`),
    getThumbnailUrl: vi.fn((wsiId: string, size = 256) => `thumb://${wsiId}?size=${size}`),
  }
})

interface MockOsdViewer {
  addHandler: ReturnType<typeof vi.fn>
  destroy: ReturnType<typeof vi.fn>
  world: {
    getItemAt: ReturnType<typeof vi.fn>
  }
}

const mockFetch = vi.mocked(fetch)

function renderViewer(wsiId: string) {
  return render(
    <TooltipProvider>
      <WSIViewer wsi_id={wsiId} />
    </TooltipProvider>
  )
}

function createMockViewer(): MockOsdViewer {
  return {
    addHandler: vi.fn(),
    destroy: vi.fn(),
    world: {
      getItemAt: vi.fn(() => ({
        getContentSize: () => ({ x: 512, y: 512 }),
      })),
    },
  }
}

describe('WSIViewer', () => {
  const sourcePath = resolve(__dirname, '../../../src/renderer/src/components/WSIViewer.tsx')
  const source = readFileSync(sourcePath, 'utf-8')

  beforeEach(() => {
    mockFetch.mockReset()
    window.OpenSeadragon = vi.fn(() => createMockViewer())
  })

  it('lazy-loads OpenSeadragon instead of importing it into the startup bundle', () => {
    expect(source).not.toMatch(/^import\s+.*['"]openseadragon['"]/m)
    expect(source).toMatch(/import\(['"]openseadragon['"]\)/)
  })

  it('shows a patch preview while the full patch image viewer is still loading', async () => {
    mockFetch.mockImplementation(async (input) => {
      const url = String(input)

      if (url.includes('/info')) {
        return new Response(JSON.stringify({ is_patch: true }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }

      if (url.includes('/heatmap')) {
        return new Response(JSON.stringify({ heatmap: [], num_patches: 0, cam: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }

      throw new Error(`Unexpected fetch URL: ${url}`)
    })

    renderViewer('patch-1')

    const preview = await screen.findByAltText('wsiViewerComponents.viewer.patchPreviewAlt')
    expect(preview).toHaveAttribute('src', 'thumb://patch-1?size=512')

    await waitFor(() => {
      expect(window.OpenSeadragon).toHaveBeenCalled()
    })
  })

  it('does not show the patch preview for tiled WSI slides', async () => {
    mockFetch.mockImplementation(async (input) => {
      const url = String(input)

      if (url.includes('/info')) {
        return new Response(JSON.stringify({ is_patch: false }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }

      if (url.includes('/dzi')) {
        return new Response('<Image TileSize="254" Overlap="1" Format="jpeg"><Size Width="1000" Height="800" /></Image>', {
          status: 200,
          headers: { 'Content-Type': 'application/xml' },
        })
      }

      if (url.includes('/heatmap')) {
        return new Response(JSON.stringify({ heatmap: [], num_patches: 0, cam: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }

      throw new Error(`Unexpected fetch URL: ${url}`)
    })

    renderViewer('wsi-1')

    await waitFor(() => {
      expect(window.OpenSeadragon).toHaveBeenCalled()
    })

    expect(screen.queryByAltText('wsiViewerComponents.viewer.patchPreviewAlt')).not.toBeInTheDocument()
  })
})
