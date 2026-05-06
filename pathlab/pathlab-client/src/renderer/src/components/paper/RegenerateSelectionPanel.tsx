import { useState } from 'react'
import { Sparkles, X } from 'lucide-react'
import { Badge } from '../ui/badge'
import { Button } from '../ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card'

export interface SelectionInfo {
  text: string
  paragraphIndex: number
}

interface RegenerateSelectionPanelProps {
  sectionName: string
  selection: SelectionInfo | null
  onClear: () => void
}

export function RegenerateSelectionPanel({ sectionName, selection, onClear }: RegenerateSelectionPanelProps) {
  const [note, setNote] = useState('')
  const [submitState, setSubmitState] = useState<'idle' | 'pending' | 'queued'>('idle')

  // Visual smoke only: real API requires Phase 2.2 (paper/phase2-2-async-regenerate)
  // to be merged. Until then, the button shows a stub state.
  const handleSubmit = () => {
    setSubmitState('pending')
    setTimeout(() => setSubmitState('queued'), 600)
  }

  const handleReset = () => {
    setNote('')
    setSubmitState('idle')
    onClear()
  }

  return (
    <Card className="border-slate-200 bg-white/95 shadow-sm xl:sticky xl:top-4">
      <CardHeader className="border-b border-slate-100 pb-3">
        <div className="flex items-center justify-between gap-2">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Regenerate</div>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Sparkles className="h-4 w-4 text-violet-500" />
              {sectionName}
            </CardTitle>
          </div>
          {selection ? (
            <Button variant="ghost" size="icon" aria-label="Clear selection" onClick={handleReset}>
              <X className="h-4 w-4" />
            </Button>
          ) : null}
        </div>
      </CardHeader>
      <CardContent className="space-y-3 py-4">
        {selection ? (
          <>
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-xs">
                <Badge variant="outline" className="bg-violet-50 text-violet-700">
                  paragraph {selection.paragraphIndex}
                </Badge>
                <span className="text-slate-400">{selection.text.length} chars</span>
              </div>
              <div className="max-h-32 overflow-y-auto rounded-xl border border-slate-100 bg-slate-50/70 p-3 text-xs italic leading-5 text-slate-600">
                "{selection.text.length > 280 ? `${selection.text.slice(0, 280)}…` : selection.text}"
              </div>
            </div>

            <label className="block">
              <span className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">Note (optional)</span>
              <textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="What should change? e.g. shorten, add a number, remove the claim about ..."
                rows={4}
                className="mt-1 w-full resize-none rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 placeholder:text-slate-400 focus:border-slate-400 focus:outline-none"
              />
            </label>

            {submitState === 'idle' ? (
              <Button className="w-full gap-2" onClick={handleSubmit}>
                <Sparkles className="h-4 w-4" />
                Regenerate paragraph
              </Button>
            ) : submitState === 'pending' ? (
              <Button className="w-full gap-2" disabled>
                <Sparkles className="h-4 w-4 animate-pulse" />
                Queueing...
              </Button>
            ) : (
              <div className="space-y-2">
                <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-700">
                  ✓ Queued. (Real backend lands with phase2-2-async-regenerate.)
                </div>
                <Button variant="outline" size="sm" className="w-full" onClick={handleReset}>
                  New selection
                </Button>
              </div>
            )}
          </>
        ) : (
          <div className="space-y-3 py-2 text-sm text-slate-500">
            <p>
              Select any paragraph in the LaTeX source on the left to regenerate it. You can optionally add a note describing
              what should change.
            </p>
            <ul className="list-disc space-y-1 pl-4 text-xs leading-5 text-slate-400">
              <li>Other paragraphs stay locked.</li>
              <li>Edits run through M10 guards + M11 refinement before saving.</li>
              <li>Backend wiring lands with Phase 2.2.</li>
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
