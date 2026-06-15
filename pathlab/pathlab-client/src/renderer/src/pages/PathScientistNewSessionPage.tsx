import { FormEvent, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus } from 'lucide-react'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { Label } from '../components/ui/label'
import { listPathScientistSkills, startPathScientistSession } from '../api/pathscientist'
import type { PathScientistSkill } from '../types/pathscientist'

const DEFAULT_MODEL = 'gpt-5.5'

export default function PathScientistNewSessionPage() {
  const navigate = useNavigate()
  const optionsRef = useRef<HTMLDivElement>(null)
  const [question, setQuestion] = useState('')
  const [skill, setSkill] = useState('')
  const [maxIter, setMaxIter] = useState(5)
  const [skills, setSkills] = useState<PathScientistSkill[]>([])
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [showAdvancedOptions, setShowAdvancedOptions] = useState(false)

  useEffect(() => {
    listPathScientistSkills()
      .then((result) => setSkills(result.items || []))
      .catch(() => setSkills([]))
  }, [])

  useEffect(() => {
    if (!showAdvancedOptions) return undefined

    const handlePointerDown = (event: MouseEvent) => {
      if (optionsRef.current?.contains(event.target as Node)) return
      setShowAdvancedOptions(false)
    }

    document.addEventListener('mousedown', handlePointerDown)
    return () => document.removeEventListener('mousedown', handlePointerDown)
  }, [showAdvancedOptions])

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    if (!question.trim()) return
    setIsSubmitting(true)
    setError('')
    try {
      const session = await startPathScientistSession({
        question: question.trim(),
        skill,
        max_iter: maxIter,
        model: DEFAULT_MODEL,
      })
      navigate(`/pathscientist/sessions/${session.session_id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start PathScientist session')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="space-y-6">
      <section className="rounded-3xl border border-gray-200 bg-white p-6 shadow-sm sm:p-8">
        <div className="mb-6">
          <h1 className="text-3xl font-extrabold tracking-tight text-gray-950">Start a PathScientist session</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-gray-500">
            Describe the computational pathology task. PathScientist will start a backend session and stream live events into the run detail page.
          </p>
        </div>

        <form className="space-y-5" onSubmit={handleSubmit}>
          <div className="space-y-2">
            <Label htmlFor="question" className="text-gray-700">Research question</Label>
            <div className="relative rounded-2xl border border-gray-200 bg-white shadow-sm transition focus-within:border-blue-300 focus-within:ring-4 focus-within:ring-blue-100">
              <textarea
                id="question"
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                className="min-h-36 w-full resize-none rounded-2xl bg-transparent px-4 pb-12 pt-3 text-sm leading-6 text-gray-900 outline-none placeholder:text-gray-400"
                placeholder="Extract Virchow2 features for this WSI folder, but do not train yet..."
              />

              <div ref={optionsRef} className="absolute bottom-2 left-2">
                <button
                  type="button"
                  onClick={() => setShowAdvancedOptions((current) => !current)}
                  aria-label="Session options"
                  aria-expanded={showAdvancedOptions}
                  className={`flex h-8 w-8 items-center justify-center rounded-full transition-colors ${
                    showAdvancedOptions
                      ? 'bg-blue-100 text-blue-700'
                      : 'text-gray-400 hover:bg-gray-100 hover:text-gray-600'
                  }`}
                >
                  <Plus className="h-4 w-4" />
                </button>

                {showAdvancedOptions && (
                  <div className="absolute bottom-full left-0 z-10 mb-2 w-72 rounded-2xl border border-gray-200 bg-white p-4 shadow-lg">
                    <div className="space-y-3">
                      <div className="space-y-2">
                        <Label htmlFor="skill" className="text-gray-700">Skill</Label>
                        <select
                          id="skill"
                          value={skill}
                          onChange={(event) => setSkill(event.target.value)}
                          className="h-10 w-full rounded-xl border border-gray-200 bg-white px-3 text-sm text-gray-900 shadow-sm outline-none transition focus:border-blue-300 focus:ring-4 focus:ring-blue-100"
                        >
                          <option value="">Auto</option>
                          {skills.map((item) => (
                            <option key={item.id} value={item.id}>{item.name}</option>
                          ))}
                        </select>
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="maxIter" className="text-gray-700">Max iter</Label>
                        <Input
                          id="maxIter"
                          type="number"
                          min={1}
                          max={20}
                          value={maxIter}
                          onChange={(event) => setMaxIter(Number(event.target.value) || 5)}
                          className="border-gray-200 bg-white text-gray-900 shadow-sm focus-visible:ring-blue-200"
                        />
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>

          {error && <div className="rounded-2xl border border-red-200 bg-red-50 p-3 text-sm font-medium text-red-700">{error}</div>}

          <div className="flex flex-col-reverse gap-3 pt-2 sm:flex-row sm:justify-end">
            <Button type="button" variant="outline" className="border-gray-200 bg-white text-gray-700 hover:bg-gray-50" onClick={() => navigate('/dashboard')}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting || !question.trim()} className="bg-blue-600 text-white shadow-sm hover:bg-blue-700">
              {isSubmitting ? 'Starting...' : 'Start session'}
            </Button>
          </div>
        </form>
      </section>
    </div>
  )
}
