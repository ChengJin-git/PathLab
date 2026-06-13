# OpenSeadragon Assets

> 随 `PathLab v1.0.4` 一起发布的本地静态资源说明。

This directory stores the static image assets bundled with PathLab's local OpenSeadragon distribution.

## What is here

- Navigation control icons used by the WSI viewer
- Assets copied into the frontend build output for direct browser/Electron loading

## How PathLab uses it

- The viewer UI is wrapped by `src/renderer/src/components/WSIViewer.tsx`
- The preprocessing service provides DZI descriptors and tiles; these assets only provide the viewer chrome
- Project-specific viewer behavior is documented in the frontend READMEs, not here

## Maintenance note

If the bundled OpenSeadragon version is updated, keep this asset directory in sync so icon paths and control images remain valid.
