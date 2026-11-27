# OpenSeadragon assets

> PathLab v1.0.8 · Updated 2026-11-06

This directory stores the static image assets bundled with PathLab's local OpenSeadragon distribution.

## What is here

- OpenSeadragon navigation control images
- Assets copied into the frontend build output for direct browser loading

## How PathLab uses it

- `src/renderer/src/components/WSIViewer.tsx` owns the OpenSeadragon instance; `components/wsiViewer/` supplies PathLab's shared toolbar and inspection panels
- The preprocessing service provides DZI descriptors and tiles; these assets only provide the viewer chrome
- `deploy/start.sh` and `deploy/hot-reload.sh frontend` both copy this asset tree into `src/renderer/dist`
- Gateway serves the copied frontend asset tree from `/assets` only when `src/renderer/dist/assets` exists
- Object editing, result layers and assistant behavior are documented in [viewer contracts](../../../../../server/backend/services/VIEWER.md)

## Maintenance note

If the bundled OpenSeadragon version is updated, keep this asset directory in sync so icon paths and control images remain valid.
