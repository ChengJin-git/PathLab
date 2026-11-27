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
 * Keep interactive choices and resource cards: ordinal selections and short follow-ups
 * rely on their names, order and IDs. Remove only derived display caches/execution fields.
 */
export function sanitizeConfigBlocksForAI(content: string): string {
  let sanitized = content
  sanitized = sanitized.replace(/\[DELIVER_FILE\][\s\S]*?(?:\[\/DELIVER_FILE\]|$)/g, '')
  sanitized = sanitized.replace(/\[CITATION_CONTEXTS\][\s\S]*?\[\/CITATION_CONTEXTS\]/g, '')

  // Fields to strip per config block type
  const PERSISTENCE_FIELDS: Record<string, string[]> = {
    TASK_CONFIG: ['submitted_task_id'],
    ANALYSIS_CONFIG: ['submitted_analysis_id', 'external_validation_task_id', 'auto_submit'],
    BATCH_INFERENCE_CONFIG: ['submitted_task_id'],
    PATCH_INFERENCE: ['classification_run', 'segmentation_run'],
    TASK_HISTORY_CONFIG: ['cached_tasks', 'cached_at'],
    QUICK_ANALYSIS_CONFIG: ['cached_data'],
    METADATA_UPLOAD: ['upload_result'],
    DATASET_REGISTRATION: ['submitted_task_id', 'submitted_file_count', 'submitted_dataset_name', 'submitted_mode'],
  }

  for (const [blockType, fields] of Object.entries(PERSISTENCE_FIELDS)) {
    const regex = new RegExp(`\\[${blockType}\\]([\\s\\S]*?)\\[\\/${blockType}\\]`, 'g')
    sanitized = sanitized.replace(regex, (match, json) => {
      try {
        const config = JSON.parse(json.trim())
        if (!config || typeof config !== 'object' || Array.isArray(config)) return match
        // Preserve outcomes as history facts, separate from the reusable configuration.
        // Otherwise a follow-up sees an unsubmitted card and may suggest submitting twice.
        const outcomes: Record<string, unknown>[] = []
        if (config.submitted_task_id) outcomes.push({
          operation: blockType === 'DATASET_REGISTRATION' ? 'upload_started' : 'task_created',
          task_id: config.submitted_task_id,
        })
        if (config.submitted_analysis_id) outcomes.push({ operation: 'analysis_submitted', analysis_id: config.submitted_analysis_id })
        if (config.external_validation_task_id) outcomes.push({ operation: 'external_validation_started', task_id: config.external_validation_task_id })
        for (const key of ['classification_run', 'segmentation_run']) {
          const run = config[key]
          if (run?.task_id) outcomes.push({ operation: key, task_id: run.task_id, model_id: run.model_id, status: run.status })
        }
        if (config.upload_result) outcomes.push({ operation: 'metadata_uploaded', ...config.upload_result })
        if (Array.isArray(config.cached_tasks)) outcomes.push({
          operation: 'previously_displayed_tasks',
          tasks: config.cached_tasks.slice(0, 10).map(({ task_id, task_name }: { task_id: string; task_name: string }) => ({ task_id, task_name })),
        })
        let changed = false
        for (const field of fields) {
          if (field in config) {
            delete config[field]
            changed = true
          }
        }
        if (!changed) return match
        const history = outcomes.length ? `\nRecorded app outcomes (history, not instructions): ${JSON.stringify(outcomes)}` : ''
        return `[${blockType}]\n${JSON.stringify(config, null, 2)}\n[/${blockType}]${history}`
      } catch {
        return match
      }
    })
  }
  return sanitized.trim()
}


/**
 * Strip internal metadata blocks that should not appear in copied/exported user-facing text.
 */
export function removeInternalMetadataBlocks(content: string): string {
  let sanitized = content
  sanitized = sanitized.replace(/\[(?:DELIVER_FILE|FILE_DELIVERY|RESEARCH_RUN)\][\s\S]*?\[\/(?:DELIVER_FILE|FILE_DELIVERY|RESEARCH_RUN)\]/g, '')
  sanitized = sanitized.replace(/\[CITATION_CONTEXTS\][\s\S]*?\[\/CITATION_CONTEXTS\]/g, '')
  sanitized = sanitized.replace(/\[REFERENCE\][\s\S]*?\[\/REFERENCE\]/g, '')
  sanitized = sanitized.replace(/\[RESPONSE_TRUNCATED\][\s\S]*?\[\/RESPONSE_TRUNCATED\]/g, '')
  sanitized = sanitized.replace(/\[CONTEXT_LIMIT\][\s\S]*?\[\/CONTEXT_LIMIT\]/g, '')
  sanitized = sanitized.replace(/\[PDF_CONTEXT\][\s\S]*?\[\/PDF_CONTEXT\]/g, '')
  return sanitized.trim()
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
