import { FormEvent, useState } from 'react'
import { answerResearchQuestion } from '../../api/autoresearch'
import { useResearchText } from './researchText'
import { Checkbox } from '../ui/checkbox'
import { Select } from '../ui/select'
import { useTranslation } from 'react-i18next'

export interface ResearchForm {
  id: string
  title: string
  fields: {
    key: string
    title?: string
    description?: string
    type: string
    required?: boolean
    hidden?: boolean
    default?: unknown
    options?: { value: string; label: string }[]
  }[]
}

export default function ResearchQuestion({
  sessionId,
  form
}: {
  sessionId: string
  form: ResearchForm
}) {
  const { text } = useResearchText()
  const { i18n } = useTranslation()
  const [values, setValues] = useState<Record<string, unknown>>(() =>
    Object.fromEntries(
      form.fields
        .filter(
          (f) =>
            f.default !== undefined ||
            f.type === 'boolean' ||
            f.type === 'multiselect'
        )
        .map((f) => [f.key, f.default ?? (f.type === 'boolean' ? false : [])])
    )
  )
  const [busy, setBusy] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState('')
  async function submit(event: FormEvent) {
    event.preventDefault()
    if(form.fields.some(field=>!field.hidden && field.required && field.type!=='boolean' &&
      (values[field.key]===undefined || values[field.key]==='' || (Array.isArray(values[field.key]) && !(values[field.key] as unknown[]).length)))) {
      setError(i18n.language.startsWith('zh') ? '请填写所有必填项。' : 'Complete all required fields.')
      return
    }
    setBusy(true)
    setError('')
    try {
      await answerResearchQuestion(sessionId, form.id, values)
      setSent(true)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <form
      onSubmit={submit}
      className="space-y-3 rounded-xl border border-blue-200 bg-blue-50 p-4"
    >
      <h3 className="text-sm font-semibold text-blue-950">{form.title}</h3>
      {form.fields
        .filter((f) => !f.hidden)
        .map((field) => (
          <div key={field.key} className="block text-sm text-gray-700">
            <label htmlFor={`${form.id}-${field.key}`}>{field.title || field.key}</label>
            {field.description && (
              <span className="mt-1 block text-xs text-gray-500">
                {field.description}
              </span>
            )}
            {field.type === 'boolean' ? (
              <Checkbox
                id={`${form.id}-${field.key}`}
                disabled={busy || sent}
                aria-label={field.title || field.key}
                className="ml-3"
                checked={Boolean(values[field.key])}
                onChange={(e) =>
                  setValues((v) => ({ ...v, [field.key]: e.target.checked }))
                }
              />
            ) : field.type === 'multiselect' ? (
              <fieldset
                aria-label={field.title || field.key}
                disabled={busy || sent}
                className="mt-2 max-h-48 space-y-1 overflow-y-auto rounded-xl border border-slate-200 bg-white p-2"
              >
                {field.options?.map((option) => (
                  <label key={option.value} className="flex min-h-10 cursor-pointer items-center gap-3 rounded-lg px-2 hover:bg-slate-50">
                    <Checkbox aria-label={option.label} checked={((values[field.key] || []) as string[]).includes(option.value)}
                      required={field.required && !((values[field.key] || []) as string[]).length}
                      onCheckedChange={checked => setValues(v => ({...v, [field.key]: checked
                        ? [...((v[field.key] || []) as string[]), option.value]
                        : ((v[field.key] || []) as string[]).filter(value => value !== option.value)}))} />
                    <span>{option.label}</span>
                  </label>
                ))}
              </fieldset>
            ) : field.options?.length ? (
              <Select id={`${form.id}-${field.key}`} ariaLabel={field.title || field.key}
                value={String(values[field.key] ?? '')} options={field.options} disabled={busy || sent}
                className="mt-2" onChange={value=>setValues(v=>({...v,[field.key]:['integer','number'].includes(field.type) ? Number(value) : value}))} />
            ) : (
              <>
                <input
                  id={`${form.id}-${field.key}`}
                  disabled={busy || sent}
                  aria-label={field.title || field.key}
                  type={
                    ['integer', 'number'].includes(field.type)
                      ? 'number'
                      : 'text'
                  }
                  required={field.required}
                  value={String(values[field.key] ?? '')}
                  onChange={(e) =>
                    setValues((v) => ({
                      ...v,
                      [field.key]: ['integer', 'number'].includes(field.type)
                        ? Number(e.target.value)
                        : e.target.value
                    }))
                  }
                  className="mt-2 w-full rounded border bg-white p-2"
                />
              </>
            )}
          </div>
        ))}
      {error && (
        <p role="alert" className="text-xs text-red-700">
          {error}
        </p>
      )}
      <button
        disabled={busy || sent}
        className="rounded-lg bg-blue-600 px-4 py-2 text-xs font-semibold text-white disabled:opacity-50"
      >
        {sent ? text.pending : text.send}
      </button>
    </form>
  )
}
