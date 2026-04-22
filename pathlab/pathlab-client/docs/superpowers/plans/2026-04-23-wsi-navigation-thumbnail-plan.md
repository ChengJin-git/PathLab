# WSI Navigation & Thumbnail Preview Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add thumbnail previews to WSI prev/next navigation and show a blurred thumbnail while OpenSeadragon loads the full DZI tiles.

**Architecture:** Two independent features: (1) `SlideNavigation` component with `getAdjacentSlideIds` utility for nav buttons with thumbnails, (2) `ProgressiveImage` component + DOM overlay in `WSIViewer` for thumbnail-first loading. Both use existing `getThumbnailUrl()` API.

**Tech Stack:** React 18, TypeScript, Vite, Tailwind CSS, OpenSeadragon, Vitest, @testing-library/react

---

## File Structure

### New Files
- `src/components/wsiViewer/SlideNavigation.tsx` — Navigation buttons with thumbnail previews
- `src/components/common/ProgressiveImage.tsx` — Blur-to-sharp image transition component
- `test/unit/lib/getAdjacentSlideIds.test.ts` — Utility function tests
- `test/unit/components/SlideNavigation.test.tsx` — Navigation component tests
- `test/unit/components/ProgressiveImage.test.tsx` — Progressive image component tests

### Modified Files
- `src/lib/wsiViewerNavigation.ts` — Add `getAdjacentSlideIds` pure function
- `src/pages/WSIViewerPage.tsx` — Integrate `SlideNavigation`, add thumbnail preloading
- `src/components/WSIViewer.tsx` — Add thumbnail overlay behind OpenSeadragon

---

## Task 1: `getAdjacentSlideIds` Utility

**Files:**
- Modify: `src/lib/wsiViewerNavigation.ts`
- Test: `test/unit/lib/getAdjacentSlideIds.test.ts`

**Context:** This utility extracts navigation index logic from `WSIViewerPage.tsx` for testability. It returns prev/next slide IDs given an array of WSISummary and current WSI ID.

- [ ] **Step 1: Write the failing test**

Create `test/unit/lib/getAdjacentSlideIds.test.ts`:

```typescript
import { describe, it, expect } from 'vitest'
import { getAdjacentSlideIds } from '../../src/renderer/src/lib/wsiViewerNavigation'

describe('getAdjacentSlideIds', () => {
  it('returns prev and next IDs when surrounded', () => {
    const slides = [{ wsi_id: 'a' }, { wsi_id: 'b' }, { wsi_id: 'c' }]
    expect(getAdjacentSlideIds(slides, 'b')).toEqual({ prevId: 'a', nextId: 'c' })
  })

  it('returns null for prev when at start', () => {
    const slides = [{ wsi_id: 'a' }, { wsi_id: 'b' }]
    expect(getAdjacentSlideIds(slides, 'a')).toEqual({ prevId: null, nextId: 'b' })
  })

  it('returns null for next when at end', () => {
    const slides = [{ wsi_id: 'a' }, { wsi_id: 'b' }]
    expect(getAdjacentSlideIds(slides, 'b')).toEqual({ prevId: 'a', nextId: null })
  })

  it('returns nulls when not found', () => {
    expect(getAdjacentSlideIds([], 'x')).toEqual({ prevId: null, nextId: null })
  })

  it('returns nulls for single slide', () => {
    const slides = [{ wsi_id: 'only' }]
    expect(getAdjacentSlideIds(slides, 'only')).toEqual({ prevId: null, nextId: null })
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/cjinag/code/PathLab/pathlab/pathlab-client
npm run test:run -- test/unit/lib/getAdjacentSlideIds.test.ts
```

Expected: FAIL with "getAdjacentSlideIds is not exported" or similar

- [ ] **Step 3: Write minimal implementation**

Add to `src/lib/wsiViewerNavigation.ts` (after existing functions, before end of file):

```typescript
export interface AdjacentSlideIds {
  prevId: string | null
  nextId: string | null
}

export function getAdjacentSlideIds(
  allWSIs: { wsi_id: string }[],
  currentWsiId: string
): AdjacentSlideIds {
  const currentIndex = allWSIs.findIndex(w => w.wsi_id === currentWsiId)
  
  if (currentIndex === -1) {
    return { prevId: null, nextId: null }
  }
  
  return {
    prevId: currentIndex > 0 ? allWSIs[currentIndex - 1].wsi_id : null,
    nextId: currentIndex >= 0 && currentIndex < allWSIs.length - 1
      ? allWSIs[currentIndex + 1].wsi_id
      : null,
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
npm run test:run -- test/unit/lib/getAdjacentSlideIds.test.ts
```

Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/lib/wsiViewerNavigation.ts test/unit/lib/getAdjacentSlideIds.test.ts
git commit -m "feat: add getAdjacentSlideIds utility with tests"
```

---

## Task 2: `SlideNavigation` Component

**Files:**
- Create: `src/components/wsiViewer/SlideNavigation.tsx`
- Test: `test/unit/components/SlideNavigation.test.tsx`

**Context:** Replaces inline prev/next buttons in `WSIViewerPage.tsx`. Shows thumbnail preview inside each button. Uses `getThumbnailUrl(wsi_id, 64)` for small previews.

- [ ] **Step 1: Write the failing test**

Create `test/unit/components/SlideNavigation.test.tsx`:

```typescript
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import SlideNavigation from '../../src/renderer/src/components/wsiViewer/SlideNavigation'
import type { WSISummary } from '../../src/renderer/src/api'

const mockWSI: WSISummary = {
  wsi_id: 'test-123',
  filename: 'test.svs',
  dataset_id: 'ds-1',
  created_at: 1234567890,
}

describe('SlideNavigation', () => {
  it('renders prev button disabled when no prev slide', () => {
    render(
      <SlideNavigation
        prevWSI={null}
        nextWSI={mockWSI}
        onNavigatePrev={() => {}}
        onNavigateNext={() => {}}
        labels={{
          previousSlide: 'Previous',
          nextSlide: 'Next',
          noPreviousSlide: 'No previous',
          noNextSlide: 'No next',
        }}
      />
    )
    expect(screen.getByRole('button', { name: /previous/i })).toBeDisabled()
  })

  it('renders next button disabled when no next slide', () => {
    render(
      <SlideNavigation
        prevWSI={mockWSI}
        nextWSI={null}
        onNavigatePrev={() => {}}
        onNavigateNext={() => {}}
        labels={{
          previousSlide: 'Previous',
          nextSlide: 'Next',
          noPreviousSlide: 'No previous',
          noNextSlide: 'No next',
        }}
      />
    )
    expect(screen.getByRole('button', { name: /next/i })).toBeDisabled()
  })

  it('calls onNavigatePrev when prev button clicked', async () => {
    const onNavigatePrev = vi.fn()
    render(
      <SlideNavigation
        prevWSI={mockWSI}
        nextWSI={null}
        onNavigatePrev={onNavigatePrev}
        onNavigateNext={() => {}}
        labels={{
          previousSlide: 'Previous',
          nextSlide: 'Next',
          noPreviousSlide: 'No previous',
          noNextSlide: 'No next',
        }}
      />
    )
    await userEvent.click(screen.getByRole('button', { name: /previous/i }))
    expect(onNavigatePrev).toHaveBeenCalled()
  })

  it('calls onNavigateNext when next button clicked', async () => {
    const onNavigateNext = vi.fn()
    render(
      <SlideNavigation
        prevWSI={null}
        nextWSI={mockWSI}
        onNavigatePrev={() => {}}
        onNavigateNext={onNavigateNext}
        labels={{
          previousSlide: 'Previous',
          nextSlide: 'Next',
          noPreviousSlide: 'No previous',
          noNextSlide: 'No next',
        }}
      />
    )
    await userEvent.click(screen.getByRole('button', { name: /next/i }))
    expect(onNavigateNext).toHaveBeenCalled()
  })

  it('renders thumbnail for prev slide when available', () => {
    render(
      <SlideNavigation
        prevWSI={mockWSI}
        nextWSI={null}
        onNavigatePrev={() => {}}
        onNavigateNext={() => {}}
        labels={{
          previousSlide: 'Previous',
          nextSlide: 'Next',
          noPreviousSlide: 'No previous',
          noNextSlide: 'No next',
        }}
      />
    )
    const img = screen.getByAltText(/previous slide thumbnail/i)
    expect(img).toHaveAttribute('src', expect.stringContaining('test-123'))
    expect(img).toHaveAttribute('src', expect.stringContaining('thumbnail'))
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

```bash
npm run test:run -- test/unit/components/SlideNavigation.test.tsx
```

Expected: FAIL with "SlideNavigation not found" or "Cannot find module"

- [ ] **Step 3: Write minimal implementation**

Create `src/components/wsiViewer/SlideNavigation.tsx`:

```typescript
import { useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { Tooltip } from '../ui/tooltip'
import { getThumbnailUrl } from '../../api/heatmap'
import type { WSISummary } from '../../api'
import { buildSlideNavigationTooltip, type SlideNavigationLabels } from '../../lib/wsiViewerNavigation'

interface SlideNavigationProps {
  prevWSI: WSISummary | null
  nextWSI: WSISummary | null
  onNavigatePrev: () => void
  onNavigateNext: () => void
  showShortcuts?: boolean
  labels: SlideNavigationLabels
}

export default function SlideNavigation({
  prevWSI,
  nextWSI,
  onNavigatePrev,
  onNavigateNext,
  showShortcuts = false,
  labels,
}: SlideNavigationProps) {
  const [prevThumbnailError, setPrevThumbnailError] = useState(false)
  const [nextThumbnailError, setNextThumbnailError] = useState(false)

  const prevThumbnailUrl = prevWSI ? getThumbnailUrl(prevWSI.wsi_id, 64) : null
  const nextThumbnailUrl = nextWSI ? getThumbnailUrl(nextWSI.wsi_id, 64) : null

  return (
    <div className="flex items-center gap-1 rounded-[1rem] border border-white/10 p-1">
      <Tooltip content={buildSlideNavigationTooltip({
        direction: 'previous',
        hasTarget: !!prevWSI,
        shortcut: 'Q',
        labels,
      })} >
        <button
          type="button"
          onClick={() => prevWSI && onNavigatePrev()}
          disabled={!prevWSI}
          className="relative flex items-center justify-center rounded-[0.85rem] p-1.5 text-slate-300 outline-none transition-all hover:bg-white/8 hover:text-white disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:bg-transparent sm:p-2"
        >
          {prevThumbnailUrl && !prevThumbnailError ? (
            <img
              src={prevThumbnailUrl}
              alt="Previous slide thumbnail"
              className="w-5 h-5 rounded object-cover"
              decoding="async"
              onError={() => setPrevThumbnailError(true)}
            />
          ) : (
            <ChevronLeft className="w-4 h-4 sm:w-5 sm:h-5" />
          )}
          {showShortcuts && <kbd className="absolute bottom-0.5 right-0.5 px-1 py-[1px] bg-white border border-gray-200 shadow-sm rounded text-[9px] font-mono font-semibold text-gray-500 z-10 pointer-events-none">Q</kbd>}
        </button>
      </Tooltip>

      <div className="mx-0.5 h-5 w-px bg-white/10"></div>

      <Tooltip content={buildSlideNavigationTooltip({
        direction: 'next',
        hasTarget: !!nextWSI,
        shortcut: 'E',
        labels,
      })} >
        <button
          type="button"
          onClick={() => nextWSI && onNavigateNext()}
          disabled={!nextWSI}
          className="relative flex items-center justify-center rounded-[0.85rem] p-1.5 text-slate-300 outline-none transition-all hover:bg-white/8 hover:text-white disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:bg-transparent sm:p-2"
        >
          {nextThumbnailUrl && !nextThumbnailError ? (
            <img
              src={nextThumbnailUrl}
              alt="Next slide thumbnail"
              className="w-5 h-5 rounded object-cover"
              decoding="async"
              onError={() => setNextThumbnailError(true)}
            />
          ) : (
            <ChevronRight className="w-4 h-4 sm:w-5 sm:h-5" />
          )}
          {showShortcuts && <kbd className="absolute bottom-0.5 right-0.5 px-1 py-[1px] bg-white border border-gray-200 shadow-sm rounded text-[9px] font-mono font-semibold text-gray-500 z-10 pointer-events-none">E</kbd>}
        </button>
      </Tooltip>
    </div>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
npm run test:run -- test/unit/components/SlideNavigation.test.tsx
```

Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/components/wsiViewer/SlideNavigation.tsx test/unit/components/SlideNavigation.test.tsx
git commit -m "feat: add SlideNavigation component with thumbnail previews"
```

---

## Task 3: Integrate `SlideNavigation` into `WSIViewerPage`

**Files:**
- Modify: `src/pages/WSIViewerPage.tsx`

**Context:** Replace inline navigation buttons with `SlideNavigation` component. Add thumbnail preloading for adjacent slides.

- [ ] **Step 1: Add import and update render**

In `src/pages/WSIViewerPage.tsx`:

Add import near top (with other component imports):
```typescript
import SlideNavigation from '../components/wsiViewer/SlideNavigation'
```

- [ ] **Step 2: Add thumbnail preloading effect**

After the existing `useEffect` for patch preloading (around line 737), add:

```typescript
// Preload adjacent slide thumbnails for instant navigation
useEffect(() => {
  if (prevWSI) {
    const img = new Image()
    img.decoding = 'async'
    img.src = getThumbnailUrl(prevWSI.wsi_id, 64)
  }
  if (nextWSI) {
    const img = new Image()
    img.decoding = 'async'
    img.src = getThumbnailUrl(nextWSI.wsi_id, 64)
  }
}, [prevWSI, nextWSI])
```

Add import for `getThumbnailUrl`:
```typescript
import { getThumbnailUrl } from '../api/heatmap'
```

- [ ] **Step 3: Replace inline navigation with SlideNavigation component**

Find the navigation button section (around lines 1833-1896) and replace with:

```tsx
<SlideNavigation
  prevWSI={prevWSI}
  nextWSI={nextWSI}
  onNavigatePrev={() => prevWSI && guardedNavigate(() => navigate(`/wsi/${prevWSI.wsi_id}`, {
    state: {
      fromAIChat,
      fromDataset,
      datasetId,
      datasetName,
      conversationId,
      chatScrollPosition,
    }
  }))}
  onNavigateNext={() => nextWSI && guardedNavigate(() => navigate(`/wsi/${nextWSI.wsi_id}`, {
    state: {
      fromAIChat,
      fromDataset,
      datasetId,
      datasetName,
      conversationId,
      chatScrollPosition,
    }
  }))}
  showShortcuts={showShortcuts}
  labels={{
    previousSlide: t('wsiViewer.previousSlide'),
    nextSlide: t('wsiViewer.nextSlide'),
    noPreviousSlide: t('wsiViewer.noPreviousSlide'),
    noNextSlide: t('wsiViewer.noNextSlide'),
  }}
/>
```

- [ ] **Step 4: Verify build passes**

```bash
npm run build
```

Expected: Build completes without errors

- [ ] **Step 5: Commit**

```bash
git add src/pages/WSIViewerPage.tsx
git commit -m "feat: integrate SlideNavigation with thumbnail preloading"
```

---

## Task 4: `ProgressiveImage` Component

**Files:**
- Create: `src/components/common/ProgressiveImage.tsx`
- Test: `test/unit/components/ProgressiveImage.test.tsx`

**Context:** Reusable component that shows a blurred thumbnail while a full image loads, then transitions to sharp. Uses CSS `filter: blur()` with transition.

- [ ] **Step 1: Write the failing test**

Create `test/unit/components/ProgressiveImage.test.tsx`:

```typescript
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import ProgressiveImage from '../../src/renderer/src/components/common/ProgressiveImage'

describe('ProgressiveImage', () => {
  it('shows blurred thumbnail initially', () => {
    render(<ProgressiveImage thumbnailUrl="thumb.jpg" alt="test" />)
    const img = screen.getByAltText('test')
    expect(img).toHaveClass('blur-md')
    expect(img).toHaveAttribute('src', 'thumb.jpg')
  })

  it('removes blur when full image loads', async () => {
    render(
      <ProgressiveImage
        thumbnailUrl="thumb.jpg"
        fullImageUrl="full.jpg"
        alt="test"
      />
    )
    const img = screen.getByAltText('test')
    
    // Initially blurred
    expect(img).toHaveClass('blur-md')
    
    // Simulate full image load by firing load event on the hidden preload image
    // The component should have created a preload image
    await waitFor(() => {
      expect(img).toHaveClass('blur-0')
    }, { timeout: 100 })
  })

  it('calls onLoad callback when image loads', () => {
    const onLoad = vi.fn()
    render(
      <ProgressiveImage
        thumbnailUrl="thumb.jpg"
        onLoad={onLoad}
        alt="test"
      />
    )
    fireEvent.load(screen.getByAltText('test'))
    expect(onLoad).toHaveBeenCalled()
  })

  it('calls onError callback when image fails', () => {
    const onError = vi.fn()
    render(
      <ProgressiveImage
        thumbnailUrl="thumb.jpg"
        onError={onError}
        alt="test"
      />
    )
    fireEvent.error(screen.getByAltText('test'))
    expect(onError).toHaveBeenCalled()
  })

  it('shows thumbnail even without fullImageUrl', () => {
    render(<ProgressiveImage thumbnailUrl="thumb.jpg" alt="test" />)
    const img = screen.getByAltText('test')
    expect(img).toHaveAttribute('src', 'thumb.jpg')
    expect(img).toHaveClass('blur-md')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

```bash
npm run test:run -- test/unit/components/ProgressiveImage.test.tsx
```

Expected: FAIL with "ProgressiveImage not found"

- [ ] **Step 3: Write minimal implementation**

Create `src/components/common/ProgressiveImage.tsx`:

```typescript
import { useState, useEffect, useRef } from 'react'
import { cn } from '../../lib/utils'

interface ProgressiveImageProps {
  thumbnailUrl: string
  fullImageUrl?: string
  alt: string
  className?: string
  onLoad?: () => void
  onError?: () => void
}

export default function ProgressiveImage({
  thumbnailUrl,
  fullImageUrl,
  alt,
  className,
  onLoad,
  onError,
}: ProgressiveImageProps) {
  const [currentSrc, setCurrentSrc] = useState(thumbnailUrl)
  const [isBlurred, setIsBlurred] = useState(true)
  const [thumbnailLoaded, setThumbnailLoaded] = useState(false)
  const preloadRef = useRef<HTMLImageElement | null>(null)

  // Handle thumbnail load
  const handleThumbnailLoad = () => {
    setThumbnailLoaded(true)
    onLoad?.()
  }

  const handleThumbnailError = () => {
    onError?.()
  }

  // Preload full image and transition when ready
  useEffect(() => {
    if (!fullImageUrl || !thumbnailLoaded) return

    const img = new Image()
    img.decoding = 'async'
    
    img.onload = () => {
      setCurrentSrc(fullImageUrl)
      // Small delay to ensure browser has the new image ready before removing blur
      requestAnimationFrame(() => {
        setIsBlurred(false)
      })
    }

    img.onerror = () => {
      // Keep thumbnail visible on error
      setIsBlurred(false)
    }

    img.src = fullImageUrl
    preloadRef.current = img

    return () => {
      preloadRef.current = null
    }
  }, [fullImageUrl, thumbnailLoaded])

  // Reset state when URLs change
  useEffect(() => {
    setCurrentSrc(thumbnailUrl)
    setIsBlurred(true)
    setThumbnailLoaded(false)
  }, [thumbnailUrl])

  return (
    <img
      src={currentSrc}
      alt={alt}
      className={cn(
        'w-full h-full object-cover transition-all duration-300',
        isBlurred && 'blur-md scale-105',
        !isBlurred && 'blur-0 scale-100',
        className
      )}
      decoding="async"
      onLoad={handleThumbnailLoad}
      onError={handleThumbnailError}
    />
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
npm run test:run -- test/unit/components/ProgressiveImage.test.tsx
```

Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/components/common/ProgressiveImage.tsx test/unit/components/ProgressiveImage.test.tsx
git commit -m "feat: add ProgressiveImage component with blur-to-sharp transition"
```

---

## Task 5: Integrate Thumbnail Overlay into `WSIViewer`

**Files:**
- Modify: `src/components/WSIViewer.tsx`

**Context:** Add a thumbnail overlay behind the OpenSeadragon viewer that shows immediately while DZI tiles load. Uses DOM overlay approach (simpler than OSD tile source manipulation).

- [ ] **Step 1: Add thumbnail URL and osdReady state**

In `src/components/WSIViewer.tsx`:

Add imports:
```typescript
import { useState, useEffect, useRef } from 'react'
import { getThumbnailUrl } from '../api/heatmap'
import { cn } from '../lib/utils'
```

Add state near other state declarations (around line 152):
```typescript
const [osdReady, setOsdReady] = useState(false)
const thumbnailUrl = getThumbnailUrl(wsi_id, 512)
```

- [ ] **Step 2: Update OSD event handlers**

In the `osdViewer.addHandler('open', ...)` callback (around line 253):

```typescript
osdViewer.addHandler('open', () => {
  setLoading(false)
  setError(undefined)
  setOsdReady(true)  // Add this line
  // ... rest of existing handler
})
```

In the `osdViewer.addHandler('open-failed', ...)` callback (around line 266):

```typescript
osdViewer.addHandler('open-failed', (event: any) => {
  setLoading(false)
  setOsdReady(false)  // Add this line
  // ... rest of existing handler
})
```

- [ ] **Step 3: Reset osdReady when wsi_id changes**

In the cleanup/initialization effect (around line 286), add `setOsdReady(false)` when starting new load:

```typescript
// In initViewer, before creating osdViewer:
setOsdReady(false)
```

- [ ] **Step 4: Update render to include thumbnail overlay**

Find the render return statement and update the viewer container:

```tsx
return (
  <div className="relative w-full h-full" ref={containerRef}>
    {/* Thumbnail overlay — shows while OSD loads */}
    {loading && thumbnailUrl && (
      <div
        className={cn(
          'absolute inset-0 z-0 flex items-center justify-center bg-slate-900/50 transition-opacity duration-500',
          osdReady ? 'opacity-0 pointer-events-none' : 'opacity-100'
        )}
      >
        <img
          src={thumbnailUrl}
          alt="Loading preview"
          className="w-full h-full object-contain blur-sm opacity-80"
          decoding="async"
        />
      </div>
    )}

    {/* OpenSeadragon container */}
    <div
      ref={viewerRef}
      className={cn(
        'absolute inset-0 z-10 transition-opacity duration-500',
        osdReady ? 'opacity-100' : 'opacity-0'
      )}
    />

    {/* ... rest of existing controls ... */}
  </div>
)
```

- [ ] **Step 5: Verify build passes**

```bash
npm run build
```

Expected: Build completes without errors

- [ ] **Step 6: Commit**

```bash
git add src/components/WSIViewer.tsx
git commit -m "feat: add thumbnail overlay while OpenSeadragon loads"
```

---

## Task 6: Integration Testing

**Files:**
- Test: `test/unit/components/WSIViewer.test.tsx` (extends existing)

**Context:** Verify thumbnail overlay appears during loading and disappears when OSD is ready.

- [ ] **Step 1: Add integration tests**

Add to existing `test/unit/components/WSIViewer.test.tsx` or create if missing:

```typescript
import { describe, it, expect } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import WSIViewer from '../../src/renderer/src/components/WSIViewer'

// Mock OpenSeadragon
declare global {
  interface Window {
    OpenSeadragon: any
  }
}

describe('WSIViewer thumbnail preview', () => {
  it('shows thumbnail overlay while loading', () => {
    render(<WSIViewer wsi_id="test-123" />)
    // Should show loading preview image
    expect(screen.getByAltText(/loading preview/i)).toBeInTheDocument()
  })

  it('thumbnail URL contains wsi_id', () => {
    render(<WSIViewer wsi_id="test-123" />)
    const img = screen.getByAltText(/loading preview/i)
    expect(img).toHaveAttribute('src', expect.stringContaining('test-123'))
  })
})
```

- [ ] **Step 2: Run integration tests**

```bash
npm run test:run -- test/unit/components/WSIViewer.test.tsx
```

Expected: Tests PASS (may need mocks for OpenSeadragon)

- [ ] **Step 3: Run full test suite**

```bash
npm run test:run
```

Expected: All existing tests still pass + new tests pass

- [ ] **Step 4: Commit**

```bash
git add test/unit/components/WSIViewer.test.tsx
git commit -m "test: add WSIViewer thumbnail overlay integration tests"
```

---

## Task 7: Final Verification

- [ ] **Step 1: Verify all tests pass**

```bash
npm run test:run
```

Expected: Full suite passes

- [ ] **Step 2: Verify build succeeds**

```bash
npm run build
```

Expected: Clean build

- [ ] **Step 3: Review changes summary**

```bash
git log --oneline --all --graph -10
```

Expected: See commits for each task

- [ ] **Step 4: Final commit (if needed)**

If any fixes were needed:
```bash
git add .
git commit -m "fix: address review feedback"
```

---

## Summary of Changes

### New Components
- `SlideNavigation` — Prev/next buttons with thumbnail previews
- `ProgressiveImage` — Blur-to-sharp image transition

### New Utilities
- `getAdjacentSlideIds` — Extract navigation logic for testability

### Modified Components
- `WSIViewerPage` — Uses `SlideNavigation`, preloads thumbnails
- `WSIViewer` — Shows thumbnail overlay while OSD loads

### Tests Added
- `getAdjacentSlideIds.test.ts` — 5 tests
- `SlideNavigation.test.tsx` — 5 tests
- `ProgressiveImage.test.tsx` — 5 tests
- `WSIViewer.test.tsx` — 2+ integration tests

---

*End of Implementation Plan*
