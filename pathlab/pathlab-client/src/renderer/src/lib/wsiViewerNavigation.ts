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

export function getAdjacentSlideIds(orderedIds: string[], currentId: string) {
  const currentIndex = orderedIds.indexOf(currentId)

  if (currentIndex === -1) {
    return {
      previousId: null,
      nextId: null,
    }
  }

  return {
    previousId: currentIndex > 0 ? orderedIds[currentIndex - 1] : null,
    nextId: currentIndex < orderedIds.length - 1 ? orderedIds[currentIndex + 1] : null,
  }
}

export function shouldPersistAnnotationsBeforeSlideNavigation(
  annotationMode: boolean,
  hasUnsavedChanges: boolean,
) {
  return annotationMode && hasUnsavedChanges
}
