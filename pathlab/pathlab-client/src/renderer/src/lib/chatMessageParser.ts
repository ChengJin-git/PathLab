/**
 * Chat message sanitization utilities.
 *
 * Extracted from AIChatPage.tsx to reduce file size.
 */

/**
 * Strip persistence-only fields from config blocks before sending message content to the AI API.
 * This prevents the AI from seeing and copying fields like submitted_task_id into new responses,
 * which would cause new config cards to initialize as already submitted.
 *
 * Also strips UI-only action blocks ([OPTIONS], [MODEL_LIST]) and metadata-only blocks
 * that should never be sent back to the model as conversation history.
 */
export function sanitizeConfigBlocksForAI(content: string): string {
  let sanitized = content
  sanitized = sanitized.replace(/\[CITATION_CONTEXTS\][\s\S]*?\[\/CITATION_CONTEXTS\]/g, '')
  sanitized = sanitized.replace(/\[OPTIONS\][\s\S]*?\[\/OPTIONS\]/g, '')
  sanitized = sanitized.replace(/\[MODEL_LIST\][\s\S]*?\[\/MODEL_LIST\]/g, '')
  sanitized = sanitized.replace(/\[PATCH_INFERENCE\][\s\S]*?\[\/PATCH_INFERENCE\]/g, '')

  // Fields to strip per config block type
  const PERSISTENCE_FIELDS: Record<string, string[]> = {
    TASK_CONFIG: ['submitted_task_id'],
    ANALYSIS_CONFIG: ['submitted_analysis_id', 'external_validation_task_id'],
    DATASET_REGISTRATION: ['submitted_task_id', 'submitted_file_count', 'submitted_dataset_name', 'submitted_mode'],
  }

  for (const [blockType, fields] of Object.entries(PERSISTENCE_FIELDS)) {
    const regex = new RegExp(`\\[${blockType}\\]([\\s\\S]*?)\\[\\/${blockType}\\]`, 'g')
    sanitized = sanitized.replace(regex, (match, json) => {
      try {
        const config = JSON.parse(json.trim())
        let changed = false
        for (const field of fields) {
          if (field in config) {
            delete config[field]
            changed = true
          }
        }
        if (!changed) return match
        return `[${blockType}]\n${JSON.stringify(config, null, 2)}\n[/${blockType}]`
      } catch {
        return match
      }
    })
  }
  return sanitized.trim()
}


export function preserveContentOnClearMarker(_content: string): string {
  return ''
}


/**
 * Check if a user message is a hidden PDF context message (not for UI display).
 * These are saved to DB by the backend to provide PDF content for follow-up questions.
 * The AI can see them in conversation history; only the UI rendering is skipped.
 */
export function isPdfContextMessage(content: string): boolean {
  const trimmed = content.trim()
  return trimmed.startsWith('[PDF_CONTEXT]') && trimmed.endsWith('[/PDF_CONTEXT]')
}

