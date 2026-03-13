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
 * Also strips frontend-only status blocks ([SEARCH_STATUS], [WEB_SEARCH_RESULT],
 * [PDF_PARSE_STATUS]) and UI-only action blocks ([OPTIONS], [MODEL_LIST]) that are
 * emitted by the backend/frontend purely for rendering during
 * streaming. If these blocks are sent back to the AI as conversation history the AI
 * will interpret them as already-available search results and refuse to perform a new
 * web search on subsequent turns.
 */
export function sanitizeConfigBlocksForAI(content: string): string {
  // Strip frontend-only streaming status blocks first.
  // These must never reach the AI model as conversation history.
  let sanitized = content
  sanitized = sanitized.replace(/\[SEARCH_STATUS\][\s\S]*?\[\/SEARCH_STATUS\]/g, '')
  sanitized = sanitized.replace(/\[WEB_SEARCH_RESULT\][\s\S]*?\[\/WEB_SEARCH_RESULT\]/g, '')
  sanitized = sanitized.replace(/\[PDF_PARSE_STATUS\][\s\S]*?\[\/PDF_PARSE_STATUS\]/g, '')
  sanitized = sanitized.replace(/\[CITATION_CONTEXTS\][\s\S]*?\[\/CITATION_CONTEXTS\]/g, '')
  sanitized = sanitized.replace(/\[OPTIONS\][\s\S]*?\[\/OPTIONS\]/g, '')
  sanitized = sanitized.replace(/\[MODEL_LIST\][\s\S]*?\[\/MODEL_LIST\]/g, '')
  sanitized = sanitized.replace(/\[PATCH_INFERENCE\][\s\S]*?\[\/PATCH_INFERENCE\]/g, '')
  sanitized = sanitized.replace(/\[DEEP_RESEARCH_LINK\][\s\S]*?\[\/DEEP_RESEARCH_LINK\]/g, '')
  sanitized = sanitized.replace(/\[TRAINING_CHAT_LINK\][\s\S]*?\[\/TRAINING_CHAT_LINK\]/g, '')

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


const STREAM_STATUS_TAGS = ['SEARCH_STATUS', 'WEB_SEARCH_RESULT', 'PDF_PARSE_STATUS'] as const

/**
 * When the backend emits __CLEAR_CONTENT__, it is asking the frontend to replace
 * previously streamed prose with a fresh restreamed answer. Preserve only the
 * UI status/result blocks that are emitted out-of-band and are NOT included in
 * the replacement prose stream (e.g. web-search status/results, PDF parse status).
 */
export function preserveContentOnClearMarker(content: string): string {
  const source = content || ''
  const preservedBlocks: string[] = []

  for (const tag of STREAM_STATUS_TAGS) {
    const regex = new RegExp(`\\[${tag}\\][\\s\\S]*?\\[\\/${tag}\\]`, 'g')
    const matches = source.match(regex)
    if (matches?.length) {
      preservedBlocks.push(...matches)
    }
  }

  return preservedBlocks.join('\n').trim()
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

