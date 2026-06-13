/**
 * VoiceControlBlock - Parse and handle [VOICE_CONTROL] blocks from AI responses
 * 
 * This block allows the AI to intelligently control whether voice input should continue
 * based on the conversation context, replacing the hardcoded NAVIGATE card detection.
 * 
 * Format:
 * [VOICE_CONTROL]
 * {
 *   "action": "continue" | "stop",
 *   "reason": "optional explanation for debugging"
 * }
 * [/VOICE_CONTROL]
 */

export interface VoiceControlConfig {
  action: 'continue' | 'stop'
  reason?: string
}

/**
 * Parse [VOICE_CONTROL] block from message content
 */
export function parseVoiceControlBlock(content: string): VoiceControlConfig | null {
  const match = content.match(/\[VOICE_CONTROL\]\s*([\s\S]*?)\s*\[\/VOICE_CONTROL\]/i)
  if (!match) return null

  try {
    const jsonStr = match[1].trim()
    const config = JSON.parse(jsonStr) as VoiceControlConfig

    // Validate required fields
    if (!config.action || !['continue', 'stop'].includes(config.action)) {
      console.warn('[VoiceControl] Invalid action:', config.action)
      return null
    }

    return config
  } catch (e) {
    console.error('[VoiceControl] Failed to parse block:', e)
    return null
  }
}

/**
 * Remove [VOICE_CONTROL] block from message content for display
 * The voice control block is for internal use only and should not be shown to users
 */
export function removeVoiceControlBlock(content: string): string {
  return content.replace(/\[VOICE_CONTROL\]\s*[\s\S]*?\s*\[\/VOICE_CONTROL\]/gi, '').trim()
}

/**
 * Check if voice should continue based on AI response
 * Returns true if voice should continue, false if it should stop
 * 
 * If no VOICE_CONTROL block is found, defaults to continuing (for backward compatibility during transition)
 */
export function shouldContinueVoice(content: string): boolean {
  const config = parseVoiceControlBlock(content)
  
  if (!config) {
    // No explicit control block - default to continue
    // This provides backward compatibility during the transition period
    return true
  }

  return config.action === 'continue'
}

