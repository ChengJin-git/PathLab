/** Structured microphone control from the current assistant stream. */
export interface VoiceControlConfig {
  action: 'continue' | 'stop'
}

/** Only a complete leading control block is executable; prose/examples are not. */
export function parseVoiceControlBlock(content: string): VoiceControlConfig | null {
  const match = content.match(/^\s*\[VOICE_CONTROL\]\s*([\s\S]*?)\s*\[\/VOICE_CONTROL\]/i)
  if (!match) return null
  try {
    const config: unknown = JSON.parse(match[1])
    if (config && typeof config === 'object' && 'action' in config &&
        (config.action === 'continue' || config.action === 'stop')) {
      return { action: config.action }
    }
  } catch { /* A malformed block is never an instruction. */ }
  return null
}

/** Hide complete and still-streaming control prefixes from the visible reply. */
export function removeVoiceControlBlock(content: string): string {
  const cleaned = content.replace(/\[VOICE_CONTROL\][\s\S]*?\[\/VOICE_CONTROL\]/gi, '')
    .replace(/^\s*\[VOICE_CONTROL\][\s\S]*$/i, '').trim()
  return cleaned && '[VOICE_CONTROL]'.startsWith(cleaned.toUpperCase()) ? '' : cleaned
}
