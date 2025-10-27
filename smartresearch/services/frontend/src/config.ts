// Use window.location.hostname to support both local and remote access
const hostname = typeof window !== 'undefined' ? window.location.hostname : '127.0.0.1'

export const API_BASE = import.meta.env.VITE_API_BASE || `http://${hostname}:6100`
export const AI_BASE  = import.meta.env.VITE_AI_BASE  || `http://${hostname}:6102/api/ai`
export const WSI_BASE = import.meta.env.VITE_WSI_BASE || `http://${hostname}:6101`

