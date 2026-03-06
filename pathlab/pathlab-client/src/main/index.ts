import { app, shell, BrowserWindow, ipcMain, dialog, session, type OpenDialogOptions } from 'electron'
import { appendFileSync, mkdirSync, existsSync } from 'fs'
import { join } from 'path'
import { electronApp, optimizer, is } from '@electron-toolkit/utils'
import { startPythonSidecar, stopPythonSidecar, getGatewayPort } from './sidecar-manager'

// Deep Link protocol
const PROTOCOL_NAME = 'pathlab'

// Disable sandbox on Linux to fix SUID sandbox helper error
if (process.platform === 'linux') {
  app.commandLine.appendSwitch('no-sandbox')
}

// Register as default protocol handler for pathlab://
// This needs to happen before app is ready
if (process.defaultApp) {
  // Development: register with path to electron executable
  if (process.argv.length >= 2) {
    app.setAsDefaultProtocolClient(PROTOCOL_NAME, process.execPath, [process.argv[1]])
  }
} else {
  // Production: register normally
  app.setAsDefaultProtocolClient(PROTOCOL_NAME)
}

// Store for pending auth callback
let pendingAuthCode: string | null = null
let mainWindow: BrowserWindow | null = null

/**
 * Handle deep link URL (pathlab://auth?code=xxx&state=yyy)
 */
function handleDeepLink(url: string): void {
  console.log('Deep link received:', url)

  try {
    const parsedUrl = new URL(url)

    // Handle auth callback: pathlab://auth?code=xxx&state=yyy
    if (parsedUrl.host === 'auth' || parsedUrl.pathname === '//auth' || parsedUrl.pathname === '/auth') {
      const code = parsedUrl.searchParams.get('code')
      const state = parsedUrl.searchParams.get('state')

      if (code) {
        console.log('Auth code received, state:', state)

        // Send to renderer process if window exists
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.webContents.send('auth-callback', { code, state })
          // Focus the window
          if (mainWindow.isMinimized()) mainWindow.restore()
          mainWindow.focus()
        } else {
          // Store for later if window not ready
          pendingAuthCode = code
        }
      }
    }
  } catch (error) {
    console.error('Error parsing deep link:', error)
  }
}

function createWindow(): void {
  // Create the browser window.
  mainWindow = new BrowserWindow({
    width: 900,
    height: 670,
    show: false,
    autoHideMenuBar: true,
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      sandbox: false
    }
  })

  // Handle permission requests for media (microphone, camera)
  session.defaultSession.setPermissionRequestHandler((webContents, permission, callback) => {
    const allowedPermissions = ['media', 'audioCapture', 'microphone']
    if (allowedPermissions.includes(permission)) {
      callback(true)
    } else {
      callback(false)
    }
  })

  mainWindow.on('ready-to-show', () => {
    mainWindow?.show()

    // Send pending auth code if exists
    if (pendingAuthCode && mainWindow) {
      mainWindow.webContents.send('auth-callback', { code: pendingAuthCode })
      pendingAuthCode = null
    }
  })

  mainWindow.webContents.setWindowOpenHandler((details) => {
    shell.openExternal(details.url)
    return { action: 'deny' }
  })

  // Prevent external URLs from navigating the main window.
  // If a link somehow bypasses e.preventDefault(), open it externally instead.
  mainWindow.webContents.on('will-navigate', (event, url) => {
    // Allow dev server and file:// URLs (internal navigation)
    const rendererUrl = process.env['ELECTRON_RENDERER_URL'] ?? ''
    if (
      url.startsWith('file://') ||
      (rendererUrl && url.startsWith(rendererUrl)) ||
      url.startsWith('http://localhost') ||
      url.startsWith('http://127.0.0.1')
    ) {
      return
    }
    // External URL — open in system browser, don't navigate the app
    event.preventDefault()
    shell.openExternal(url)
  })

  // HMR for renderer base on electron-vite cli.
  // Load the remote URL for development or the local html file for production.
  if (is.dev && process.env['ELECTRON_RENDERER_URL']) {
    mainWindow.loadURL(process.env['ELECTRON_RENDERER_URL'])
  } else {
    mainWindow.loadFile(join(__dirname, '../renderer/index.html'))
  }
}

// Handle deep links on macOS (when app is already running)
app.on('open-url', (event, url) => {
  event.preventDefault()
  handleDeepLink(url)
})

// Handle deep links on Windows/Linux (single instance)
const gotTheLock = app.requestSingleInstanceLock()

if (!gotTheLock) {
  app.quit()
} else {
  app.on('second-instance', (_event, commandLine) => {
    // Windows/Linux: deep link URL is in command line args
    const url = commandLine.find(arg => arg.startsWith(`${PROTOCOL_NAME}://`))
    if (url) {
      handleDeepLink(url)
    }

    // Focus window if exists
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore()
      mainWindow.focus()
    }
  })
}

// IPC handler for renderer to open external login URL
ipcMain.handle('open-external-url', async (_event, url: string) => {
  await shell.openExternal(url)
})

// IPC handler for renderer to get gateway port
ipcMain.handle('get-gateway-port', () => {
  return getGatewayPort()
})

// IPC handler for file selection
ipcMain.handle('select-files', async (_event, options?: { title?: string; filters?: { name: string; extensions: string[] }[] }) => {
  const dialogOptions: OpenDialogOptions = {
    title: options?.title || 'Select files',
    properties: ['openFile', 'multiSelections'],
    filters: options?.filters
  }
  const result = mainWindow
    ? await dialog.showOpenDialog(mainWindow, dialogOptions)
    : await dialog.showOpenDialog(dialogOptions)
  if (result.canceled) return []
  return result.filePaths
})

// IPC handler for appending Deep Research frontend logs to a local file
ipcMain.handle('append-dr-logs', (_event, text: string) => {
  try {
    const logDir = join(process.cwd(), 'server', 'backend', 'logs')
    if (!existsSync(logDir)) {
      mkdirSync(logDir, { recursive: true })
    }
    const logFile = join(logDir, 'deep-research-frontend.log')
    appendFileSync(logFile, text, 'utf-8')
    return true
  } catch (err) {
    console.error('[Main] Failed to write DR frontend logs:', err)
    return false
  }
})

// IPC handler for directory selection
ipcMain.handle('select-directory', async (_event, options?: { title?: string }) => {
  const dialogOptions: OpenDialogOptions = {
    title: options?.title || 'Select directory',
    properties: ['openDirectory']
  }
  const result = mainWindow
    ? await dialog.showOpenDialog(mainWindow, dialogOptions)
    : await dialog.showOpenDialog(dialogOptions)
  if (result.canceled || result.filePaths.length === 0) return null
  return result.filePaths[0]
})

// This method will be called when Electron has finished
// initialization and is ready to create browser windows.
// Some APIs can only be used after this event occurs.
app.whenReady().then(() => {
  // Set app user model id for windows
  electronApp.setAppUserModelId('com.pathlab.client')

  // Default open or close DevTools by F12 in development
  // and ignore CommandOrControl + R in production.
  // see https://github.com/alex8088/electron-toolkit/tree/master/packages/utils
  app.on('browser-window-created', (_, window) => {
    optimizer.watchWindowShortcuts(window)
  })

  // Start Python sidecar and wait for port discovery
  startPythonSidecar()
    .then((port) => {
      console.log(`[Main] Python sidecar started on port ${port}`)
    })
    .catch((error) => {
      console.error('[Main] Failed to start Python sidecar:', error)
    })

  createWindow()

  app.on('activate', function () {
    // On macOS it's common to re-create a window in the app when the
    // dock icon is clicked and there are no other windows open.
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })

  // Handle deep link if app was launched with one (macOS cold start)
  const url = process.argv.find(arg => arg.startsWith(`${PROTOCOL_NAME}://`))
  if (url) {
    handleDeepLink(url)
  }
})

// Quit when all windows are closed, except on macOS. There, it's common
// for applications and their menu bar to stay active until the user quits
// explicitly with Cmd + Q.
app.on('window-all-closed', () => {
  stopPythonSidecar()
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('before-quit', () => {
    stopPythonSidecar()
})
