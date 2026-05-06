import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Loader2, Trash2 } from 'lucide-react'
import { deletePaperRun } from '../../api/papers'
import { Button } from '../ui/button'
import { ModalShell } from '../ui/modal-shell'

interface DeleteRunButtonProps {
  paperId: string
  onDeleted: () => void
}

export function DeleteRunButton({ paperId, onDeleted }: DeleteRunButtonProps) {
  const [confirmOpen, setConfirmOpen] = useState(false)
  const qc = useQueryClient()
  const deleteMutation = useMutation({
    mutationFn: () => deletePaperRun(paperId),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['paper-runs'] })
      onDeleted()
    },
  })

  return (
    <>
      <Button variant="destructive" size="sm" className="gap-2" onClick={() => setConfirmOpen(true)}>
        <Trash2 className="h-4 w-4" />
        Delete
      </Button>
      <ModalShell isOpen={confirmOpen} onClose={() => setConfirmOpen(false)} title="Delete paper run">
        <div className="space-y-4 p-5">
          <div className="flex items-start gap-2 text-sm text-red-800">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <h3 className="text-base font-semibold text-slate-950">Delete this paper run?</h3>
              <p className="mt-1 text-sm leading-6 text-slate-500">
                This action cannot be undone from the frontend. Run ID: {paperId}
              </p>
            </div>
          </div>
          {deleteMutation.error ? (
            <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              {deleteMutation.error instanceof Error ? deleteMutation.error.message : String(deleteMutation.error)}
            </div>
          ) : null}
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>
              Keep run
            </Button>
            <Button variant="destructive" className="gap-2" onClick={() => deleteMutation.mutate()} disabled={deleteMutation.isPending}>
              {deleteMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
              Delete
            </Button>
          </div>
        </div>
      </ModalShell>
    </>
  )
}
