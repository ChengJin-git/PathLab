type AutoResearchStandaloneEnv = {
  VITE_AUTORESEARCH_STANDALONE?: unknown
  VITE_DEBUG?: unknown
  [key: string]: unknown
}

export function isAutoResearchStandaloneMode(
  env: AutoResearchStandaloneEnv = import.meta.env,
): boolean {
  return env.VITE_AUTORESEARCH_STANDALONE === 'true' || env.VITE_DEBUG === 'true'
}
