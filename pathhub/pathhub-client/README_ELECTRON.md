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
*   Spawn the Python sidecar (`python/main.py`) automatically.

## Building for Production

1.  **Build Python Sidecar:**
    ```bash
    ./build-python.sh
    ```
    This creates `python/dist/main`.

2.  **Build Electron App:**
    ```bash
    npm run build
    ```
    This packages the Electron app and includes the Python executable.

## Architecture

*   **Main Process**: `src/main/index.ts` - Manages the window and the Python sidecar.
*   **Sidecar Manager**: `src/main/sidecar-manager.ts` - Spawns/Kills the Python process.
*   **Renderer**: `services/frontend` - The existing React application.
*   **Python Sidecar**: `python/main.py` - A FastAPI app providing:
    *   `/health`: Status check.
    *   `/tile/{z}/{x}/{y}`: Mock tile server for WSI visualization.
    *   `/inference`: Mock inference endpoint returning random masks.

## Notes

*   The `electron.vite.config.ts` is configured to use `services/frontend` as the renderer root.
*   `DashboardPage.tsx` includes a status indicator for the Python sidecar.
*   `WSIViewer.tsx` is configured to use the mock tile server and includes a "Mock Analyze" button.
