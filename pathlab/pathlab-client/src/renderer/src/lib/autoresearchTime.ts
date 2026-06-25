export function formatAutoResearchElapsed(createdAt?: number, nowMs: number = Date.now()): string {
  if (!createdAt) return ''
  const totalSeconds = Math.max(0, Math.floor(nowMs / 1000 - createdAt))
  if (totalSeconds < 60) return `${totalSeconds}s`
  const seconds = totalSeconds % 60
  const totalMinutes = Math.floor(totalSeconds / 60)
  if (totalMinutes < 60) return `${totalMinutes}m ${seconds}s`
  const minutes = totalMinutes % 60
  const hours = Math.floor(totalMinutes / 60)
  if (hours < 24) return `${hours}h ${minutes}m`
  const days = Math.floor(hours / 24)
  const dayHours = hours % 24
  return `${days}d ${dayHours}h`
}
