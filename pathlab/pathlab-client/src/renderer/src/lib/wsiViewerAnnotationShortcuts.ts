export function isEditableTarget(target: EventTarget | null): boolean {
  const el = target instanceof HTMLElement ? target : null
  if (!el) return false
  const tag = el.tagName
  return (
    tag === 'INPUT' ||
    tag === 'TEXTAREA' ||
    Boolean(el.isContentEditable) ||
    el.getAttribute('contenteditable') === 'true' ||
    el.hasAttribute('contenteditable')
  )
}

export function getLabelFromDigitShortcut(code: string, visibleLabels: string[], key?: string): string | null {
  const match = code.match(/^Digit([1-9])$/)
  const fallback = key?.match(/^[1-9]$/)
  const digit = match?.[1] ?? fallback?.[0]
  if (!digit) return null
  const idx = Number(digit) - 1
  return visibleLabels[idx] ?? null
}
