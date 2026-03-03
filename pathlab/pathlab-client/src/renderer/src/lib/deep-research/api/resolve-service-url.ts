import { API_BASE } from '../../../config';

/**
 * Resolve deep-research service URL through PathLab gateway.
 * Routes through /agent/research/* prefix on the gateway.
 */
export function resolveServiceURL(path: string) {
  // Map deep-research paths to gateway proxy paths
  // deep-research: chat/stream -> gateway: /agent/research/chat/stream (raw SSE proxy)
  const cleanPath = path.replace(/^\.?\/?(api\/)?/, '');
  return `${API_BASE}/agent/research/${cleanPath}`;
}

/**
 * Get auth headers for gateway requests.
 * Uses the same token key as the main PathLab API.
 */
export function getAuthHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  const token = localStorage.getItem('pathlab_auth_token');
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}
