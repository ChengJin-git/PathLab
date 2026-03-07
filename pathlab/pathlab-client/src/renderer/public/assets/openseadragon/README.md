# OpenSeadragon Assets

This directory stores the static image assets bundled with PathLab's local OpenSeadragon distribution.

## What is here

- Navigation control icons used by the WSI viewer
- Assets served from Vite `public/` and copied into frontend build output for browser / Electron loading

## How PathLab uses it

- The viewer UI is wrapped by `src/renderer/src/components/WSIViewer.tsx`
- The full-screen viewer entry is `src/renderer/src/pages/WSIViewerPage.tsx`
- The preprocessing service provides DZI descriptors and tiles; these assets only provide viewer chrome and controls
- Project-specific viewer behavior is documented in the frontend READMEs, not here

## Maintenance note

If the bundled OpenSeadragon version is updated, keep this asset directory in sync so icon paths and control images remain valid.
