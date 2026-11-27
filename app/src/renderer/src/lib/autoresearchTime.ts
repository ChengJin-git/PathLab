export function formatAutoResearchElapsed(createdAt?: number, nowMs: number = Date.now(), locale = 'en-US'): string {
  if (createdAt === undefined || createdAt === null || !Number.isFinite(createdAt)) return ''
  const unit = (value: number, unit: string) => new Intl.NumberFormat(locale, {style: 'unit', unit, unitDisplay: 'short'}).format(value)
  const totalSeconds = Math.max(0, Math.floor(nowMs / 1000 - createdAt))
  if (totalSeconds < 60) return unit(totalSeconds, 'second')
  const seconds = totalSeconds % 60
  const totalMinutes = Math.floor(totalSeconds / 60)
  if (totalMinutes < 60) return `${unit(totalMinutes, 'minute')} ${unit(seconds, 'second')}`
  const minutes = totalMinutes % 60
  const hours = Math.floor(totalMinutes / 60)
  if (hours < 24) return `${unit(hours, 'hour')} ${unit(minutes, 'minute')}`
  const days = Math.floor(hours / 24)
  const dayHours = hours % 24
  return `${unit(days, 'day')} ${unit(dayHours, 'hour')}`
}
