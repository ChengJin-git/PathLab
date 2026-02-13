/**
 * Chat message sanitization utilities.
 *
 * Extracted from AIChatPage.tsx to reduce file size.
 */

/**
 * Strip persistence-only fields from config blocks before sending message content to the AI API.
 * This prevents the AI from seeing and copying fields like submitted_task_id into new responses,
 * which would cause new config cards to initialize as already submitted.
 */
export function sanitizeConfigBlocksForAI(content: string): string {
  // Fields to strip per config block type
  const PERSISTENCE_FIELDS: Record<string, string[]> = {
    TASK_CONFIG: ['submitted_task_id'],
    INFERENCE_CONFIG: ['submitted_task_id'],
    ANALYSIS_CONFIG: ['submitted_analysis_id', 'external_validation_task_id'],
    DATASET_REGISTRATION: ['submitted_task_id', 'submitted_file_count', 'submitted_dataset_name', 'submitted_mode'],
  }

  let sanitized = content
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
  return sanitized
}

