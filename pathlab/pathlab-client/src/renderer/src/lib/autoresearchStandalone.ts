type AutoResearchStandaloneEnv = {
  VITE_AUTORESEARCH_STANDALONE?: unknown
  VITE_DEBUG?: unknown
  [key: string]: unknown
}

interface AutoResearchStandaloneOptions {
  isElectron: boolean
  env?: AutoResearchStandaloneEnv
}

export function isAutoResearchStandaloneMode({
  isElectron,
  env = import.meta.env,
}: AutoResearchStandaloneOptions): boolean {
  if (isElectron) return false

  return env.VITE_AUTORESEARCH_STANDALONE === 'true' || env.VITE_DEBUG === 'true'
}
