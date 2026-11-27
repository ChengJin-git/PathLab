export interface ResearchStep {
  id?: string
  title: string
  status: string
  phase?: string
  summary?: string
  children?: { title: string; status: string }[]
}

export const researchStepKey = (step: ResearchStep) => step.id || step.title

export function researchPlanState(plan: ResearchStep[], status: string) {
  const live = ['running', 'waiting', 'preparing'].includes(status)
  const active = live ? plan.filter(step => step.status === 'running') : []
  const completed = plan.filter(step => step.status === 'completed').length
  return { active, completed, total: plan.length }
}

export function researchStepStatus(status: string, sessionStatus: string) {
  if (status !== 'running' || ['running', 'waiting', 'preparing', 'pausing'].includes(sessionStatus)) return status
  return sessionStatus === 'paused' ? 'paused' : 'interrupted'
}
