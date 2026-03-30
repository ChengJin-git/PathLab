import { app } from 'electron'
import { spawn, ChildProcess } from 'child_process'
import { join } from 'path'
import { mkdirSync, existsSync, chmodSync, readdirSync, rmSync } from 'fs'
import * as net from 'net'

export interface EmbeddedServiceUrls {
  databaseUrl: string
  redisUrl: string
}

function findFreePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = net.createServer()
    server.listen(0, '127.0.0.1', () => {
      const addr = server.address() as net.AddressInfo
      server.close(() => resolve(addr.port))
    })
    server.on('error', reject)
  })
}

function waitForPort(port: number, timeoutMs = 30000): Promise<void> {
  const deadline = Date.now() + timeoutMs
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const conn = net.createConnection(port, '127.0.0.1')
      conn.setTimeout(500)
      conn.on('connect', () => {
        conn.destroy()
        resolve()
      })
      conn.on('error', () => {
        conn.destroy()
        if (Date.now() >= deadline) {
          reject(new Error(`Port ${port} not available after ${timeoutMs}ms`))
        } else {
          setTimeout(attempt, 300)
        }
      })
      conn.on('timeout', () => {
        conn.destroy()
        if (Date.now() >= deadline) {
          reject(new Error(`Timeout waiting for port ${port}`))
        } else {
          setTimeout(attempt, 300)
        }
      })
    }
    setTimeout(attempt, 500)
  })
}

let redisProcess: ChildProcess | null = null
let redisPort = 0

async function startRedis(): Promise<string> {
  redisPort = await findFreePort()

  const dataDir = join(app.getPath('userData'), 'redis-data')
  mkdirSync(dataDir, { recursive: true })

  const redisBinaryName = process.platform === 'win32' ? 'redis-server.exe' : 'redis-server'
  const redisBinary = app.isPackaged
    ? join(process.resourcesPath, redisBinaryName)
    : join(process.cwd(), 'resources', redisBinaryName)

  if (!existsSync(redisBinary)) {
    throw new Error(
      `Redis binary not found: ${redisBinary}\nRun: bash scripts/prepare-redis.sh`
    )
  }

  try {
    chmodSync(redisBinary, 0o755)
  } catch (_) {
    // ignore on read-only filesystems
  }

  const redisArgs = process.platform === 'win32'
    ? [
        '--port', String(redisPort),
        '--address', '127.0.0.1',
      ]
    : [
        '--port', String(redisPort),
        '--bind', '127.0.0.1',
        '--dir', dataDir,
        '--appendonly', 'yes',
        '--appendfilename', 'pathlab.aof',
        '--loglevel', 'warning',
        '--daemonize', 'no',
      ]

  redisProcess = spawn(redisBinary, redisArgs, { stdio: ['ignore', 'pipe', 'pipe'] })

  redisProcess.stdout?.on('data', (d: Buffer) => console.log('[Redis]', d.toString().trim()))
  redisProcess.stderr?.on('data', (d: Buffer) => console.log('[Redis]', d.toString().trim()))
  redisProcess.on('error', (e) => console.error('[Redis] Process error:', e))

  await waitForPort(redisPort, 15000)
  console.log(`[Redis] Started on port ${redisPort}`)
  return `redis://127.0.0.1:${redisPort}/0`
}

function stopRedis(): void {
  if (redisProcess) {
    redisProcess.kill('SIGTERM')
    redisProcess = null
  }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
let pgInstance: any = null
let pgPort = 0

async function startPostgres(): Promise<string> {
  pgPort = await findFreePort()

  const dataDir = join(app.getPath('userData'), 'postgres-data')
  mkdirSync(dataDir, { recursive: true })

  const { default: EmbeddedPostgres } = await import('embedded-postgres')
  const pgLogs: string[] = []

  pgInstance = new EmbeddedPostgres({
    databaseDir: dataDir,
    user: 'pathlab',
    password: 'pathlab',
    port: pgPort,
    persistent: true,
    onLog: (msg: string) => { pgLogs.push(msg); console.log('[PostgreSQL]', msg) },
    onError: (msg: unknown) => { pgLogs.push(`ERROR: ${String(msg)}`); console.error('[PostgreSQL]', msg) }
  })

  const pgVersionFile = join(dataDir, 'PG_VERSION')
  if (!existsSync(pgVersionFile)) {
    // Clean up partial initialization from a previous failed run
    if (existsSync(dataDir) && readdirSync(dataDir).length > 0) {
      console.log('[PostgreSQL] Cleaning up partial postgres-data directory...')
      rmSync(dataDir, { recursive: true, force: true })
      mkdirSync(dataDir, { recursive: true })
    }
    console.log('[PostgreSQL] Initializing database cluster (first run)...')
    try {
      await pgInstance.initialise()
    } catch (e) {
      const reason = e instanceof Error ? e.message : String(e)
      const logs = pgLogs.slice(-10).join('\n')
      throw new Error(`PostgreSQL init failed: ${reason}\n${logs}`)
    }
  }

  try {
    await pgInstance.start()
  } catch (e) {
    const reason = e instanceof Error ? e.message : String(e)
    const logs = pgLogs.slice(-10).join('\n')
    throw new Error(`PostgreSQL start failed: ${reason}\n${logs}`)
  }

  try {
    await pgInstance.createDatabase('pathlab')
    console.log('[PostgreSQL] Database "pathlab" created')
  } catch (_) {
    // database already exists on subsequent runs
  }

  console.log(`[PostgreSQL] Started on port ${pgPort}`)
  return `postgresql+asyncpg://pathlab:pathlab@127.0.0.1:${pgPort}/pathlab`
}

async function stopPostgres(): Promise<void> {
  if (pgInstance) {
    try {
      await pgInstance.stop()
    } catch (e) {
      console.error('[PostgreSQL] Error during stop:', e)
    }
    pgInstance = null
  }
}

export async function startEmbeddedServices(): Promise<EmbeddedServiceUrls> {
  console.log('[Services] Starting embedded Redis and PostgreSQL...')
  const [redisUrl, databaseUrl] = await Promise.all([startRedis(), startPostgres()])
  console.log('[Services] All embedded services ready')
  return { databaseUrl, redisUrl }
}

export function stopEmbeddedServices(): void {
  stopRedis()
  stopPostgres().catch((e) => console.error('[Services] PostgreSQL stop error:', e))
}
