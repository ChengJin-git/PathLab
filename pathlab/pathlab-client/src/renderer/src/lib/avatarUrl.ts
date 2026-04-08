import { API_BASE } from '../config'

function getBackendBase(): string {
  return API_BASE.replace(/\/+$/, '').replace(/\/api$/, '')
}

export function resolveAvatarUrl(avatarUrl: string | null | undefined): string | null {
  if (!avatarUrl) return null
  if (avatarUrl.startsWith('http')) return avatarUrl
  return `${getBackendBase()}${avatarUrl}`
}
