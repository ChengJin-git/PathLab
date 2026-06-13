/**
 * Parse VRAM-related error messages and extract suggested batch_size.
 * Returns structured error info for better user feedback.
 */
export function parseTaskError(errorMessage: string): {
  isVRAMError: boolean
  isStorageError: boolean
  suggestedBatchSize: number | null
  originalMessage: string
  userFriendlyMessage: string
  suggestion: string | null
} {
  const result = {
    isVRAMError: false,
    isStorageError: false,
    suggestedBatchSize: null as number | null,
    originalMessage: errorMessage,
    userFriendlyMessage: errorMessage,
    suggestion: null as string | null,
  }

  const lower = errorMessage.toLowerCase()

  // Check for external storage connectivity errors
  if (lower.includes('external storage not responding') ||
      (lower.includes('storage') && lower.includes('timed out')) ||
      (lower.includes('not accessible') && lower.includes('file')) ||
      lower.includes('mount point') || lower.includes('network storage')) {
    result.isStorageError = true
    result.userFriendlyMessage = 'The storage appears to be unreachable.'
    result.suggestion = 'Please contact the administrator to check the storage device connection.'
    return result
  }

  // Check if this is a VRAM protection error
  if (lower.includes('vram') || lower.includes('gpu memory') ||
      lower.includes('out of memory') || lower.includes('oom')) {
    result.isVRAMError = true

    // Try to extract suggested batch_size from error message
    const batchSizeMatch = errorMessage.match(/batch_size[:\s]+(\d+)|batch_size to (\d+)/i)
    if (batchSizeMatch) {
      result.suggestedBatchSize = parseInt(batchSizeMatch[1] || batchSizeMatch[2], 10)
    }

    result.userFriendlyMessage = result.suggestedBatchSize
      ? `GPU memory exceeded. Please reduce the batch size to ${result.suggestedBatchSize} or lower and try again.`
      : 'GPU memory exceeded. Please reduce the batch size and try again.'
  }

  return result
}

