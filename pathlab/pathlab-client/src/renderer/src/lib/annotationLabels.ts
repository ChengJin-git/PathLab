import type { AnnotationsMap } from '../api/annotation'

export function deriveAnnotationLabels(
  annotations: AnnotationsMap,
  rememberedLabels: string[],
): string[] {
  const labels = new Set<string>()
  for (const regions of Object.values(annotations)) {
    for (const region of regions) {
      const label = region.label.trim()
      if (label) labels.add(label)
    }
  }
  for (const label of rememberedLabels) {
    const trimmed = label.trim()
    if (trimmed) labels.add(trimmed)
  }
  return Array.from(labels)
}

export function isMissingCurrentLabel(currentLabel: string, visibleLabels: string[]): boolean {
  const trimmed = currentLabel.trim()
  return trimmed.length > 0 && !visibleLabels.includes(trimmed)
}
