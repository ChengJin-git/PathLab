# PathHub Client (Electron)

This directory contains the Electron-based client for PathHub.

## Setup

1.  **Install Node Dependencies:**
    ```bash
    npm install
    ```

2.  **Install Python Dependencies:**
    ```bash
    pip install fastapi uvicorn pillow
    # If you want to build the executable:
    pip install pyinstaller
    ```

## Development

To start the application in development mode (Electron + React + Python Sidecar):

```bash
npm run dev
```

This will:
*   Start the Vite dev server for the renderer.
*   Start the Electron main process.
*   Spawn the Python sidecar (`server/main.py`) automatically.

## Building for Production

### 1. Build Python Sidecar (Critical Step)
**Important:** PyInstaller builds an executable for the **current operating system**.
*   To build for **Windows**, you must run this on Windows (or use Wine).
*   To build for **Linux**, run on Linux.
*   To build for **macOS**, run on macOS.

```bash
# On the target OS:
pip install pyinstaller
./build-python.sh  # (Or run the pyinstaller command manually on Windows)
```
This creates `server/dist/main` (or `main.exe` on Windows).

### 2. Package Electron App
Once the Python executable is ready in `server/dist/`, run the build command for your target:

```bash
# Build for Linux (AppImage, deb)
npm run build:linux

# Build for Windows (nsis installer)
# Note: Can be run on Linux/macOS if you have the server/dist/main.exe ready
npm run build:win

# Build for macOS (dmg)
# Note: Must be run on macOS for code signing
npm run build:mac
```

The output files (installers) will be in the `dist/` directory.

## Architecture

*   **Main Process**: `src/main/index.ts` - Manages the window and the Python sidecar.
*   **Sidecar Manager**: `src/main/sidecar-manager.ts` - Spawns/Kills the Python process.
*   **Renderer**: `src/renderer` - The React application.
*   **Python Sidecar**: `server/main.py` - A FastAPI app providing:
    *   `/health`: Status check.
    *   `/tile/{z}/{x}/{y}`: Mock tile server for WSI visualization.
    *   `/inference`: Mock inference endpoint returning random masks.

## Notes

*   The `electron.vite.config.ts` is configured to use `services/frontend` as the renderer root.
*   `DashboardPage.tsx` includes a status indicator for the Python sidecar.
*   `WSIViewer.tsx` is configured to use the mock tile server and includes a "Mock Analyze" button.
