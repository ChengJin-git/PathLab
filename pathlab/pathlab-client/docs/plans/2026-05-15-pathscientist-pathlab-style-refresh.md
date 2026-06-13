# PathScientist PathLab Style Refresh Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Restyle the existing PathScientist MVP pages so they feel native to PathLab instead of a separate dark console.

**Architecture:** Keep the existing `/pathscientist/*` routes and API behavior. Replace only presentation classes/structure in the PathScientist layout, session list, new-session form, and session detail pages using existing PathLab visual primitives: white headers, gray page background, blue primary accents, rounded cards, and soft shadows.

**Tech Stack:** React, TypeScript, Tailwind CSS, existing PathLab UI primitives.

---

### Task 1: Layout Shell

**Files:**
- Modify: `src/renderer/src/components/pathscientist/PathScientistLayout.tsx`

**Steps:**
1. Replace dark full-screen background with `bg-gray-50` / `text-gray-900`.
2. Add PathLab logo in a white translucent sticky header.
3. Keep Sessions/New navigation, restyled as PathLab rounded pills.
4. Verify `/pathscientist` still renders.

### Task 2: Session List Page

**Files:**
- Modify: `src/renderer/src/pages/PathScientistSessionsPage.tsx`

**Steps:**
1. Replace dark hero with a white page header and subtle blue gradient badge.
2. Restyle loading/error/empty states as white cards with gray/blue accents.
3. Restyle session rows as PathLab card links.
4. Verify list and refresh behavior remains unchanged.

### Task 3: New Session Page

**Files:**
- Modify: `src/renderer/src/pages/PathScientistNewSessionPage.tsx`

**Steps:**
1. Replace dark form card with a white card and PathLab field styling.
2. Add a small info side panel for model/default behavior.
3. Keep existing form state and submit behavior unchanged.
4. Verify create flow still navigates to the session detail route.

### Task 4: Session Detail Page

**Files:**
- Modify: `src/renderer/src/pages/PathScientistSessionPage.tsx`

**Steps:**
1. Replace dark panels with white dashboard cards.
2. Keep summary metrics, event stream, and raw state layout.
3. Use blue/green/red status pills rather than cyan-on-black.
4. Verify SSE rendering and JSON display still work.

### Task 5: Verification

**Commands:**
```bash
cd /project/vcompath/storage/ywangrm/PathLab/pathlab/pathlab-client
npm run test:run -- test/unit/api/pathscientist.test.ts
npx --no-install tsc -p tsconfig.json --noEmit
```
