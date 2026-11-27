import type { ExternalAvailability } from '../api/wsi'

export function isExternalUnavailable(
  record: { availability?: ExternalAvailability | null }
): boolean {
  return record.availability?.status === 'unavailable'
}

export function getExternalUnavailableReason(
  record: { availability?: ExternalAvailability | null }
): string | undefined {
  return record.availability?.reason ?? undefined
}
