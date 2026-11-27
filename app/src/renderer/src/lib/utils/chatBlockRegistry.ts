export const FUNCTIONAL_CARD_INCOMPLETE_TAGS = new Set([
  'TASK_CONFIG', 'ANALYSIS_CONFIG', 'IMAGE_RECOMMENDATION', 'PATCH_INFERENCE',
  'QUICK_ANALYSIS_CONFIG', 'METRIC_CONFIG', 'CHART_CONFIG', 'OPTIONS',
])

export const SPECIAL_BLOCK_TAGS = [
  'LOAD_CONNECTOR', 'CONNECTOR_TOOL', 'LOAD_SKILL', 'SEARCH_FILES',
  'DELIVER_FILE', 'FILE_DELIVERY', 'RESEARCH_RUN',
  'OPTIONS',
  'TASK_CONFIG',
  'IMAGE_RECOMMENDATION',
  'CSV_ACTION',
  'NAVIGATE',
  'ANALYSIS_CONFIG',
  'METRIC_CONFIG',
  'CHART_CONFIG',
  'QUICK_ANALYSIS_CONFIG',
  'CSV_PREVIEW',
  'CANCEL_TASK',
  'RENAME_TASK',
  'TASK_HISTORY_CONFIG',
  'VOICE_CONTROL',
  'SUBMIT_TASK',
  'CANCEL_TASK_NOW',
  'DATASET_REGISTRATION',
  'DATASET_EDIT',
  'METADATA_UPLOAD',
  'MODEL_LIST',
  'PATCH_INFERENCE',
  'BATCH_INFERENCE_CONFIG',
  'BATCH_INFERENCE_SUMMARY',
  'REFERENCE',
  'PDF_PARSE_STATUS',
  'SEARCH_STATUS',
  'WEB_SEARCH_RESULT',
  'WEB_SEARCH',
  'READ_ARTICLE',
  'LOAD_CAPABILITY',
  'CITATION_CONTEXTS',
]

export function getIncompleteBlock(
  content: string,
  isStreaming: boolean = false,
): { content: string; incompleteTag: string | null } {
  let result = content
  let incompleteTag: string | null = null

  for (const tag of SPECIAL_BLOCK_TAGS) {
    const openTag = `[${tag}]`
    const closeTag = `[/${tag}]`
    const openIndex = result.indexOf(openTag)

    if (openIndex !== -1 && result.indexOf(closeTag) === -1) {
      result = result.substring(0, openIndex).trim()
      incompleteTag = tag
      break
    }
  }

  if (isStreaming && !incompleteTag) {
    const lastBracket = result.lastIndexOf('[')
    if (lastBracket !== -1) {
      const trailing = result.substring(lastBracket)
      if (!trailing.includes(']')) {
        const partialTag = trailing.substring(1)
        if (partialTag.length > 0) {
          for (const tag of SPECIAL_BLOCK_TAGS) {
            if (tag.startsWith(partialTag)) {
              result = result.substring(0, lastBracket).trim()
              incompleteTag = tag
              break
            }
          }
        }
      }
    }
  }

  if (!isStreaming) {
    incompleteTag = null
  }

  return { content: result, incompleteTag }
}
