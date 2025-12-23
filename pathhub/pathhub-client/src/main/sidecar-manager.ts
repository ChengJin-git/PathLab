import { spawn, ChildProcess } from 'child_process'
import { join } from 'path'
import { app } from 'electron'

let pythonProcess: ChildProcess | null = null

export function startPythonSidecar(): void {
  // In production, this will be different. For now, assume dev.
  // We might need to detect if we are in dev or prod.
  const isDev = !app.isPackaged
  
  let pythonPath = 'python3'
  let scriptPath = ''
  
  if (isDev) {
    // Assuming running from project root
    scriptPath = join(process.cwd(), 'server/main.py')
  } else {
    // In production, we will use the bundled executable
    // This is a placeholder for Step 3
    scriptPath = join(process.resourcesPath, 'server/main') 
  }

  console.log(`Starting Python sidecar: ${pythonPath} ${scriptPath}`)

  pythonProcess = spawn(pythonPath, [scriptPath])

  pythonProcess.stdout?.on('data', (data) => {
    console.log(`[Python]: ${data}`)
  })

  pythonProcess.stderr?.on('data', (data) => {
    console.error(`[Python Error]: ${data}`)
  })

  pythonProcess.on('close', (code) => {
    console.log(`Python process exited with code ${code}`)
    pythonProcess = null
  })
}

export function stopPythonSidecar(): void {
  if (pythonProcess) {
    console.log('Stopping Python sidecar...')
    pythonProcess.kill()
    pythonProcess = null
  }
}
