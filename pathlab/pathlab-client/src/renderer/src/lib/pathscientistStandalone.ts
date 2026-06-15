type PathScientistStandaloneEnv = {
  VITE_PATHSCIENTIST_STANDALONE?: unknown
  VITE_DEBUG?: unknown
  [key: string]: unknown
}

interface PathScientistStandaloneOptions {
  isElectron: boolean
  env?: PathScientistStandaloneEnv
}

export function isPathScientistStandaloneMode({
  isElectron,
  env = import.meta.env,
}: PathScientistStandaloneOptions): boolean {
  if (isElectron) return false

  return env.VITE_PATHSCIENTIST_STANDALONE === 'true' || env.VITE_DEBUG === 'true'
}
