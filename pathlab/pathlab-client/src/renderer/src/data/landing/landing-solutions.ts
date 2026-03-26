import { SolutionTabKey } from "../../types/landing"
import { Stethoscope, FlaskConical, Building2 } from 'lucide-react'

export const SOLUTIONS_TABS: { key: SolutionTabKey; labelKey: string; descKey: string; bulletKeys: string[]; icon: any }[] = [
  {
    key: 'clinician',
    labelKey: 'landing.solutions.clinician.label',
    descKey: 'landing.solutions.clinician.desc',
    icon: Stethoscope,
    bulletKeys: [
      'landing.solutions.clinician.bullet1',
      'landing.solutions.clinician.bullet2',
      'landing.solutions.clinician.bullet3'
    ]
  },
  {
    key: 'researcher',
    labelKey: 'landing.solutions.researcher.label',
    descKey: 'landing.solutions.researcher.desc',
    icon: FlaskConical,
    bulletKeys: [
      'landing.solutions.researcher.bullet1',
      'landing.solutions.researcher.bullet2',
      'landing.solutions.researcher.bullet3'
    ]
  },
  {
    key: 'institution',
    labelKey: 'landing.solutions.institution.label',
    descKey: 'landing.solutions.institution.desc',
    icon: Building2,
    bulletKeys: [
      'landing.solutions.institution.bullet1',
      'landing.solutions.institution.bullet2',
      'landing.solutions.institution.bullet3'
    ]
  }
]
