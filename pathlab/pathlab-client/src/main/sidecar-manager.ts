import { spawn, ChildProcess } from 'child_process'
import { join } from 'path'
import { app, BrowserWindow } from 'electron'

let pythonProcess: ChildProcess | null = null

export interface BackendServicePorts {
  gateway: number | null
  preprocessing: number | null
  ai: number | null
}

let servicePorts: BackendServicePorts = {
  gateway: null,
  preprocessing: null,
  ai: null
}

/**
 * Parse PORT=<number> from process output
 */
function parseGatewayPort(line: string): number | null {
  const match = line.match(/PORT=(\d+)/)
  if (match) {
    return parseInt(match[1], 10)
  }
  return null
}

/**
 * Parse [Services] Gateway: <port>, Preprocessing: <port>, AI: <port>
 */
function parseServicePorts(line: string): BackendServicePorts | null {
  const match = line.match(/\[Services\]\s*Gateway:\s*(\d+),\s*Preprocessing:\s*(\d+),\s*AI:\s*(\d+)/)
  if (!match) {
    return null
  }

  return {
    gateway: parseInt(match[1], 10),
    preprocessing: parseInt(match[2], 10),
    ai: parseInt(match[3], 10)
  }
}

function notifyRendererWindows(): void {
  BrowserWindow.getAllWindows().forEach((win) => {
    win.webContents.send('backend-service-ports', { ...servicePorts })
    if (servicePorts.gateway) {
      win.webContents.send('gateway-port', servicePorts.gateway)
    }
  })
}

function updateServicePorts(nextPorts: Partial<BackendServicePorts>): void {
  let changed = false

  for (const [key, value] of Object.entries(nextPorts) as Array<[keyof BackendServicePorts, number | null]>) {
    if (value !== null && servicePorts[key] !== value) {
      servicePorts = {
        ...servicePorts,
        [key]: value
      }
      changed = true
    }
  }

  if (changed) {
    notifyRendererWindows()
  }
}

/**
 * Get the discovered gateway port
 */
export function getGatewayPort(): number | null {
  return servicePorts.gateway
}

/**
 * Get all discovered backend service ports
 */
export function getServicePorts(): BackendServicePorts {
  return { ...servicePorts }
}

export function startPythonSidecar(extraEnv?: Record<string, string>): Promise<number> {
  return new Promise((resolve, reject) => {
    const isDev = !app.isPackaged

    let pythonPath = 'python3'
    let scriptPath = ''

    if (isDev) {
      scriptPath = join(process.cwd(), 'server/main.py')
      process.env.PATHLAB_DEV = '0'
    } else {
      const exeSuffix = process.platform === 'win32' ? '.exe' : ''
      pythonPath = join(process.resourcesPath, 'server', 'main', `main${exeSuffix}`)
      scriptPath = ''
    }

    console.log(`Starting Python sidecar: ${pythonPath} ${scriptPath}`)

    const spawnEnv = { ...process.env, ...extraEnv }

    if (isDev) {
      pythonProcess = spawn(pythonPath, [scriptPath], {
        env: spawnEnv,
        stdio: ['pipe', 'pipe', 'pipe']
      })
    } else {
      pythonProcess = spawn(pythonPath, [], {
        env: spawnEnv,
        stdio: ['pipe', 'pipe', 'pipe']
      })
    }

    servicePorts = {
      gateway: null,
      preprocessing: null,
      ai: null
    }

    let portResolved = false
    let stdoutBuffer = ''
    const timeout = setTimeout(() => {
      if (!portResolved) {
        reject(new Error('Timeout waiting for Python sidecar to start'))
      }
    }, 30000) // 30 second timeout

    const resolveGatewayPort = (port: number): void => {
      updateServicePorts({ gateway: port })

      if (!portResolved) {
        portResolved = true
        clearTimeout(timeout)
        console.log(`[Sidecar] Gateway port discovered: ${port}, waiting for /health...`)
        // Poll Gateway /health until it returns 200 (Gateway takes 5-20 s to init DB/Redis)
        const healthUrl = `http://127.0.0.1:${port}/health`
        const healthDeadline = Date.now() + 60000  // 60 s hard cap
        const pollHealth = (): void => {
          if (Date.now() > healthDeadline) {
            console.error(`[Sidecar] Gateway /health did not become ready within 60 s`)
            resolve(port)  // resolve anyway so Electron does not hang
            return
          }
          const http = require('http') as typeof import('http')
          const req = http.get(healthUrl, (res) => {
            res.resume()
            if (res.statusCode === 200) {
              console.log(`[Sidecar] Gateway is ready on port ${port}`)
              resolve(port)
            } else {
              setTimeout(pollHealth, 500)
            }
          })
          req.on('error', () => setTimeout(pollHealth, 500))
          req.setTimeout(1000, () => { req.destroy(); setTimeout(pollHealth, 500) })
        }
        pollHealth()
      }
    }

    const handleOutputLine = (line: string): void => {
      const services = parseServicePorts(line)
      if (services) {
        updateServicePorts(services)
        if (services.gateway) {
          resolveGatewayPort(services.gateway)
        }
      }

      const gatewayPort = parseGatewayPort(line)
      if (gatewayPort) {
        resolveGatewayPort(gatewayPort)
      }
    }

    pythonProcess.stdout?.on('data', (data) => {
      const output = data.toString()
      console.log(`[Python]: ${output}`)

      stdoutBuffer += output
      const lines = stdoutBuffer.split(/\r?\n/)
      stdoutBuffer = lines.pop() || ''

      for (const line of lines) {
        handleOutputLine(line)
      }
    })

    pythonProcess.stderr?.on('data', (data) => {
      // uvicorn logs to stderr, so this is normal output
      console.log(`[Python]: ${data}`)
    })

    pythonProcess.on('error', (error) => {
      console.error(`[Python Error]: Failed to start process:`, error)
      if (!portResolved) {
        clearTimeout(timeout)
        reject(error)
      }
    })

    pythonProcess.on('close', (code) => {
      console.log(`Python process exited with code ${code}`)
      pythonProcess = null
      servicePorts = {
        gateway: null,
        preprocessing: null,
        ai: null
      }
    })
  })
}

export function stopPythonSidecar(): void {
  if (pythonProcess) {
    console.log('Stopping Python sidecar...')
    pythonProcess.kill()
    pythonProcess = null
    servicePorts = {
      gateway: null,
      preprocessing: null,
      ai: null
    }
  }
}
