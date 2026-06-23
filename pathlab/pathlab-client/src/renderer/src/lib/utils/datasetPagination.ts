export interface ClampDatasetPageInput {
  isError: boolean
  isFetching: boolean
  hasQueryData: boolean
}

export function clampDatasetPage(
  currentPage: number,
  totalPages: number,
  input: ClampDatasetPageInput
): number {
  if (input.isError) {
    return currentPage
  }

  if (input.isFetching && !input.hasQueryData) {
    return currentPage
  }

  return Math.min(currentPage, totalPages)
}

export function clampFilePage(
  currentPage: number,
  totalPages: number,
  input: ClampDatasetPageInput
): number {
  if (input.isError) {
    return currentPage
  }

  if (input.isFetching && !input.hasQueryData) {
    return currentPage
  }

  return Math.min(currentPage, totalPages)
}
