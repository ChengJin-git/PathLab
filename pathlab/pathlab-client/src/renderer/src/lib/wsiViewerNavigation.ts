export type SlideNavigationDirection = 'previous' | 'next'

export interface SlideNavigationLabels {
  previousSlide: string
  nextSlide: string
  noPreviousSlide: string
  noNextSlide: string
}

export function buildSlideNavigationTooltip({
  direction,
  hasTarget,
  shortcut,
  labels,
}: {
  direction: SlideNavigationDirection
  hasTarget: boolean
  shortcut: string
  labels: SlideNavigationLabels
}) {
  if (direction === 'previous') {
    return hasTarget ? `${labels.previousSlide} (${shortcut})` : labels.noPreviousSlide
  }

  return hasTarget ? `${labels.nextSlide} (${shortcut})` : labels.noNextSlide
}

export function shouldPersistAnnotationsBeforeSlideNavigation(
  annotationMode: boolean,
  hasUnsavedChanges: boolean,
) {
  return annotationMode && hasUnsavedChanges
}
