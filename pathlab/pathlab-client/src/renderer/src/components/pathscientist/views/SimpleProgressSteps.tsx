import { Check, Circle, Loader2, XCircle } from 'lucide-react'
import { usePathScientistTranslation } from '../../../lib/usePathScientistTranslation'
import type { ClinicalProgressStep } from '../../../lib/pathscientistClinicalSteps'

interface SimpleProgressStepsProps {
  steps: ClinicalProgressStep[]
}

function statusIcon(status: ClinicalProgressStep['status']) {
  if (status === 'complete') return <Check className="h-4 w-4" />
  if (status === 'error') return <XCircle className="h-4 w-4" />
  if (status === 'current') return <Loader2 className="h-4 w-4 animate-spin" />
  return <Circle className="h-4 w-4" />
}

function statusClasses(status: ClinicalProgressStep['status']) {
  switch (status) {
    case 'complete':
      return 'border-emerald-200 bg-emerald-50 text-emerald-700'
    case 'error':
      return 'border-red-200 bg-red-50 text-red-700'
    case 'current':
      return 'border-blue-200 bg-blue-50 text-blue-700 shadow-sm'
    default:
      return 'border-gray-200 bg-white text-gray-400'
  }
}

export default function SimpleProgressSteps({ steps }: SimpleProgressStepsProps) {
  const { t } = usePathScientistTranslation()

  return (
    <section className="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm" data-testid="pathscientist-clinical-progress">
      <h2 className="text-sm font-bold text-gray-900">{t('pathScientist.clinical.progressTitle')}</h2>
      <ol className="mt-4 space-y-3">
        {steps.map((step, index) => (
          <li key={step.id} className="flex gap-3">
            <div className="flex flex-col items-center">
              <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full border ring-1 ring-inset ${statusClasses(step.status)}`}>
                {statusIcon(step.status)}
              </div>
              {index < steps.length - 1 && <div className="mt-1 h-full min-h-6 w-px bg-gray-200" />}
            </div>
            <div className="min-w-0 flex-1 pb-1">
              <p className="text-sm font-semibold text-gray-900">{t(step.labelKey)}</p>
              {step.summary && (
                <p className="mt-1 text-sm leading-6 text-gray-500">{step.summary}</p>
              )}
            </div>
          </li>
        ))}
      </ol>
    </section>
  )
}
