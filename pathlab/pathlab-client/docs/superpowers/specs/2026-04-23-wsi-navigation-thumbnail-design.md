# WSI Navigation & Thumbnail Preview Design

> **Date**: 2026-04-23  
> **Scope**: PathLab Client (React 18 + TypeScript + Vite + Tailwind + OpenSeadragon)  
> **Status**: Design Document — No Code Changes  
> **Author**: AI Assistant  

---

## 1. Overview

This document specifies two complementary enhancements to the WSI (Whole Slide Image) viewer experience in PathLab:

1. **Lightweight prev/next navigation with thumbnail previews** — Show thumbnail previews in navigation buttons and make slide transitions feel instant by preloading adjacent slide data.
2. **Thumbnail-first image preview** — Show a low-resolution thumbnail immediately while the full DZI tile source loads in OpenSeadragon, with a smooth blur-to-sharp transition.

Both features use existing API endpoints (`getThumbnailUrl`, `getRecommendationThumbnailUrl`) and follow established patterns in the PathLab codebase.

---

## 2. Goals & Non-Goals

### Goals
- Reduce perceived loading time when switching between slides
- Provide visual context for prev/next navigation
- Improve perceived performance of WSI viewer initialization
- Maintain full testability with TDD sequencing
- Use existing APIs without backend changes

### Non-Goals
- No backend API changes
- No new dependencies (build custom lightweight components)
- No changes to OpenSeadragon core behavior
- No prefetching of full WSI summaries (only thumbnails)

---

## 3. Existing Architecture

### Current Navigation (WSIViewerPage.tsx)
```typescript
const currentIndex = allWSIs.findIndex(w => w.wsi_id === wsi_id)
const prevWSI = currentIndex > 0 ? allWSIs[currentIndex - 1] : null
const nextWSI = currentIndex >= 0 && currentIndex < allWSIs.length - 1 ? allWSIs[currentIndex + 1] : null
```

- Navigation uses React Router `navigate()` with full page transition
- Keyboard shortcuts Q/E trigger navigation with annotation persistence check
- Navigation buttons are simple `<button>` elements with Chevron icons
- `slideNavRef` stores prev/next WSI references for keyboard handler

### Current WSI Loading (WSIViewer.tsx)
```typescript
// Initialization flow:
// 1. Fetch /heatmap/wsi/{id}/info to determine patch vs WSI
// 2. For WSI: fetch DZI XML, parse dimensions
// 3. Create OpenSeadragon viewer with DZI tile source
// 4. Show Loader2 spinner until 'open' event fires
```

- Shows loading spinner (`Loader2`) while OpenSeadragon initializes
- No thumbnail preview during loading
- `onSlideInfo` callback exposes dimensions to parent

### Existing Thumbnail APIs (api/heatmap.ts)
```typescript
export function getThumbnailUrl(wsi_id: string, size: number = 256): string
export function getRecommendationThumbnailUrl(wsi_id: string, size: number = 160): string
```

- URLs include auth token via `withAuthTokenQuery`
- Can request arbitrary sizes (e.g., 64px for nav buttons, 512px for preview)

---

## 4. Design: Feature 1 — Prev/Next Navigation with Thumbnails

### 4.1 Component: `SlideNavigation`

**Location**: `src/components/wsiViewer/SlideNavigation.tsx`

**Props Interface**:
```typescript
interface SlideNavigationProps {
  prevWSI: WSISummary | null
  nextWSI: WSISummary | null
  onNavigatePrev: () => void
  onNavigateNext: () => void
  showShortcuts?: boolean
  labels: SlideNavigationLabels
}
```

**Behavior**:
- Renders two navigation buttons (prev/next) with thumbnail previews
- Thumbnails fetched via `getThumbnailUrl(wsi_id, 64)` for button preview
- Thumbnails use `decoding="async"` to prevent main thread blocking
- Buttons disabled when no adjacent slide exists
- Keyboard shortcuts (Q/E) handled by parent (WSIViewerPage)

**Visual Design**:
```
┌─────────────────────────────────────┐
│  [◀︎ thumbnail]  |  [thumbnail ▶︎]  │
│   prev slide        next slide      │
└─────────────────────────────────────┘
```

- Thumbnail shown as small circular or rounded-square preview inside button
- Fallback to Chevron icon if thumbnail fails to load
- Tooltip shows slide name + keyboard shortcut (existing behavior)

### 4.2 Pure Function: `getAdjacentSlideIds`

**Location**: `src/lib/wsiViewerNavigation.ts` (extends existing module)

```typescript
export function getAdjacentSlideIds(
  allWSIs: WSISummary[],
  currentWsiId: string
): { prevId: string | null; nextId: string | null } {
  const currentIndex = allWSIs.findIndex(w => w.wsi_id === currentWsiId)
  return {
    prevId: currentIndex > 0 ? allWSIs[currentIndex - 1].wsi_id : null,
    nextId: currentIndex >= 0 && currentIndex < allWSIs.length - 1 
      ? allWSIs[currentIndex + 1].wsi_id 
      : null,
  }
}
```

**Rationale**: Extract navigation logic from component for testability.

### 4.3 Integration with WSIViewerPage

Replace inline navigation buttons with `<SlideNavigation>` component:

```typescript
// In WSIViewerPage.tsx render:
<SlideNavigation
  prevWSI={prevWSI}
  nextWSI={nextWSI}
  onNavigatePrev={handleNavigatePrev}
  onNavigateNext={handleNavigateNext}
  showShortcuts={showShortcuts}
  labels={navigationLabels}
/>
```

### 4.4 Preloading Strategy

**Thumbnail Preloading**:
```typescript
// In WSIViewerPage.tsx — preload adjacent thumbnails when current slide changes
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

**Rationale**: Preload thumbnails so they're cached when user hovers/clicks. Uses existing pattern already in codebase (see patch preview preloading at line 727-737).

---

## 5. Design: Feature 2 — Thumbnail-First Image Preview

### 5.1 Component: `ProgressiveImage`

**Location**: `src/components/common/ProgressiveImage.tsx`

**Props Interface**:
```typescript
interface ProgressiveImageProps {
  thumbnailUrl: string      // Low-res thumbnail URL (e.g., 256px)
  fullImageUrl?: string     // Optional full image URL (for non-OSD contexts)
  alt: string
  className?: string
  onLoad?: () => void
  onError?: () => void
}
```

**State Machine**:
```
[LOADING_THUMBNAIL] → [THUMBNAIL_READY] → [LOADING_FULL] → [FULL_READY]
       ↓                      ↓                  ↓               ↓
   show spinner          show blurred       blur + load    sharp image
                           thumbnail        full image     no blur
```

**Implementation Strategy**:

1. **Initial render**: Show thumbnail with CSS `filter: blur(8px)` and `transform: scale(1.05)`
2. **Thumbnail load**: When `onLoad` fires on thumbnail `<img>`, keep blur but show image
3. **Full image preload**: Create `new Image()` with `fullImageUrl`, wait for `onload`
4. **Transition**: Swap `src` to full image, remove blur with CSS transition (`transition: filter 0.3s ease-out`)

**CSS Approach** (Tailwind):
```tsx
<img
  src={currentSrc}
  alt={alt}
  className={cn(
    "w-full h-full object-cover transition-all duration-300",
    isBlurred && "blur-md scale-105",
    !isBlurred && "blur-0 scale-100"
  )}
  decoding="async"
/>
```

### 5.2 Integration with WSIViewer

**OpenSeadragon Thumbnail-First Strategy**:

Per OpenSeadragon maintainer (iangilman), the recommended approach for thumbnail-to-full transition is:

1. Load thumbnail as a simple image tile source **behind** the main DZI tile source
2. Fade from thumbnail to full tiles once loaded

**Implementation in WSIViewer.tsx**:

```typescript
// During initialization (after DZI info is fetched):
const thumbnailUrl = getThumbnailUrl(wsi_id, 512)

// Add thumbnail as simple image tile source (lower opacity, behind DZI)
osdViewer.addTiledImage({
  tileSource: {
    type: 'image',
    url: thumbnailUrl,
    buildPyramid: false,
  },
  opacity: 1,
  success: (event: any) => {
    const thumbnailImage = event.item
    
    // Add DZI tile source on top
    osdViewer.addTiledImage({
      tileSource: {
        width: dzi.width,
        height: dzi.height,
        tileSize: dzi.tileSize,
        tileOverlap: dzi.overlap,
        getTileUrl: (level: number, x: number, y: number) => {
          return `${tileUrlBase}/${level}/${x}_${y}.${dzi.format}`
        }
      },
      opacity: 0, // Start invisible
      success: (event: any) => {
        const dziImage = event.item
        
        // Fade in DZI as tiles load
        dziImage.setOpacity(1)
        
        // Optionally fade out thumbnail once DZI is fully loaded
        dziImage.addHandler('fully-loaded-change', () => {
          if (dziImage.getFullyLoaded()) {
            thumbnailImage.setOpacity(0)
          }
        })
      }
    })
  }
})
```

**Alternative Simpler Approach** (Recommended for PathLab):

Instead of OSD-level tile source manipulation, use a DOM overlay:

1. Place a `<div>` with thumbnail `<img>` **behind** the OpenSeadragon viewer container
2. When OSD fires `'open'` event, fade out the thumbnail overlay
3. This avoids OSD API complexity and is easier to test

```tsx
// In WSIViewer.tsx render:
<div className="relative w-full h-full">
  {/* Thumbnail overlay — behind OSD */}
  {loading && thumbnailUrl && (
    <div 
      className={cn(
        "absolute inset-0 z-0 transition-opacity duration-500",
        osdReady ? "opacity-0" : "opacity-100"
      )}
    >
      <img
        src={thumbnailUrl}
        alt="Loading preview"
        className="w-full h-full object-contain blur-sm"
        decoding="async"
      />
    </div>
  )}
  
  {/* OpenSeadragon container */}
  <div 
    ref={viewerRef}
    className={cn(
      "absolute inset-0 z-10 transition-opacity duration-500",
      osdReady ? "opacity-100" : "opacity-0"
    )}
  />
</div>
```

**Recommendation**: Use the DOM overlay approach. It's simpler, doesn't require OSD API manipulation, and is fully testable.

---

## 6. Testing Strategy (TDD Sequencing)

### Phase 1: Pure Navigation Utilities

**Test file**: `test/unit/lib/getAdjacentSlideIds.test.ts`

```typescript
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
})
```

### Phase 2: SlideNavigation Component

**Test file**: `test/unit/components/SlideNavigation.test.tsx`

```typescript
describe('SlideNavigation', () => {
  it('renders prev button disabled when no prev slide', () => {
    render(<SlideNavigation prevWSI={null} nextWSI={mockWSI} ... />)
    expect(screen.getByRole('button', { name: /previous/i })).toBeDisabled()
  })

  it('renders thumbnail for prev slide when available', () => {
    render(<SlideNavigation prevWSI={mockWSI} nextWSI={null} ... />)
    const img = screen.getByAltText(/previous slide thumbnail/i)
    expect(img).toHaveAttribute('src', expect.stringContaining('thumbnail'))
  })

  it('calls onNavigatePrev when prev button clicked', async () => {
    const onNavigatePrev = vi.fn()
    render(<SlideNavigation prevWSI={mockWSI} onNavigatePrev={onNavigatePrev} ... />)
    await userEvent.click(screen.getByRole('button', { name: /previous/i }))
    expect(onNavigatePrev).toHaveBeenCalled()
  })

  it('shows fallback icon when thumbnail fails to load', () => {
    render(<SlideNavigation prevWSI={mockWSI} ... />)
    const img = screen.getByAltText(/previous slide thumbnail/i)
    fireEvent.error(img)
    expect(screen.getByTestId('chevron-left-icon')).toBeInTheDocument()
  })
})
```

### Phase 3: ProgressiveImage Component

**Test file**: `test/unit/components/ProgressiveImage.test.tsx`

```typescript
describe('ProgressiveImage', () => {
  it('shows blurred thumbnail initially', () => {
    render(<ProgressiveImage thumbnailUrl="thumb.jpg" alt="test" />)
    const img = screen.getByAltText('test')
    expect(img).toHaveClass('blur-md')
  })

  it('removes blur when full image loads', async () => {
    render(<ProgressiveImage thumbnailUrl="thumb.jpg" fullImageUrl="full.jpg" alt="test" />)
    const img = screen.getByAltText('test')
    
    // Simulate full image load
    await waitFor(() => {
      expect(img).toHaveClass('blur-0')
    })
  })

  it('calls onLoad callback when image loads', () => {
    const onLoad = vi.fn()
    render(<ProgressiveImage thumbnailUrl="thumb.jpg" onLoad={onLoad} alt="test" />)
    fireEvent.load(screen.getByAltText('test'))
    expect(onLoad).toHaveBeenCalled()
  })
})
```

### Phase 4: WSIViewer Integration

**Test file**: `test/unit/components/WSIViewer.test.tsx` (extends existing)

```typescript
describe('WSIViewer thumbnail preview', () => {
  it('shows thumbnail overlay while loading', () => {
    render(<WSIViewer wsi_id="test-123" />)
    expect(screen.getByAltText(/loading preview/i)).toBeInTheDocument()
  })

  it('hides thumbnail when OpenSeadragon is ready', async () => {
    render(<WSIViewer wsi_id="test-123" />)
    
    // Simulate OSD open event
    await waitFor(() => {
      expect(screen.queryByAltText(/loading preview/i)).not.toBeInTheDocument()
    })
  })
})
```

---

## 7. API Compatibility

### Existing APIs Used

| API | Purpose | Size Used |
|-----|---------|-----------|
| `getThumbnailUrl(wsi_id, 64)` | Nav button thumbnails | 64px |
| `getThumbnailUrl(wsi_id, 512)` | WSI viewer preview | 512px |
| `getRecommendationThumbnailUrl(wsi_id, 160)` | Alternative small preview | 160px |

### No Backend Changes Required

All thumbnail URLs are constructed client-side using existing `buildAuthedHeatmapUrl` helper. The backend already supports arbitrary `size` parameters.

---

## 8. Performance Considerations

### Image Loading
- Use `decoding="async"` on all thumbnail `<img>` elements
- Preload adjacent slide thumbnails on slide change
- Use `loading="lazy"` for thumbnails below the fold (not applicable for nav buttons)

### Memory
- Thumbnail images are small (64px ≈ 2-5KB, 512px ≈ 20-50KB)
- Browser naturally evicts unused images from memory
- No explicit cache management needed

### OpenSeadragon
- DOM overlay approach doesn't add extra OSD tile sources
- No additional tile loading overhead
- Fade transition is CSS-only (GPU accelerated)

---

## 9. Error Handling

### Thumbnail Load Failures
- Show fallback Chevron icon if thumbnail fails to load
- Log warning to console (non-blocking)
- Navigation remains functional

### Full Image Load Failures
- Keep thumbnail visible (blurred) if full image fails
- Show error state after timeout (e.g., 10 seconds)
- User can still navigate away

### OpenSeadragon Failures
- If OSD fails to initialize, thumbnail remains visible with error overlay
- Existing error handling in WSIViewer.tsx preserved

---

## 10. Implementation Order

1. **Phase 1**: `getAdjacentSlideIds` utility + tests
2. **Phase 2**: `SlideNavigation` component + tests
3. **Phase 3**: Integrate `SlideNavigation` into `WSIViewerPage`
4. **Phase 4**: `ProgressiveImage` component + tests
5. **Phase 5**: Integrate thumbnail overlay into `WSIViewer`
6. **Phase 6**: Add thumbnail preloading to `WSIViewerPage`
7. **Phase 7**: Integration testing & manual QA

---

## 11. Files to Create/Modify

### New Files
```
src/components/wsiViewer/SlideNavigation.tsx
src/components/common/ProgressiveImage.tsx
test/unit/lib/getAdjacentSlideIds.test.ts
test/unit/components/SlideNavigation.test.tsx
test/unit/components/ProgressiveImage.test.tsx
```

### Modified Files
```
src/lib/wsiViewerNavigation.ts          # Add getAdjacentSlideIds
src/pages/WSIViewerPage.tsx             # Use SlideNavigation, add preloading
src/components/WSIViewer.tsx            # Add thumbnail overlay
```

---

## 12. References

- **OpenSeadragon thumbnail strategy**: [Issue #2262](https://github.com/openseadragon/openseadragon/issues/2262) — iangilman recommends loading simple image behind DZI
- **Progressive image loading pattern**: [React SME Cookbook](https://reactdevelopers.org/docs/images-icons/image-placeholders) — LQIP with CSS blur
- **OpenSeadragon fade example**: [CodePen YXRLea](https://codepen.io/iangilman/pen/YXRLea) — fading between two images
- **Existing preload pattern**: WSIViewerPage.tsx lines 727-737 (patch preview preloading)
- **Existing cache system**: `src/lib/cache.ts` with `createCache`, `createKeyedCache`

---

## 13. Open Questions

1. **Thumbnail size for nav buttons**: 64px sufficient or should we use 128px for retina displays?
2. **Transition duration**: 300ms feels right, but should be configurable?
3. **Should we cache thumbnail URLs** in a keyed cache like other API responses?
4. **Mobile experience**: Should nav buttons be larger on touch devices?

---

*End of Design Document*
