import { describe, expect, it } from 'vitest'
import { normalizeForMatch, pdfMatchSection } from './pdfSectionMatch'

const sections = [
  {
    section_name: 'introduction',
    text: String.raw`
Digital pathology workflows increasingly use whole-slide images for clinical decision support.
Our contribution is an evidence-locked paper generation workspace for reproducible reporting.
`,
  },
  {
    section_name: 'methods',
    text: String.raw`
The model uses \textbf{multiple instance learning} over tiles and aggregates slide-level features.
We train the pipeline with deterministic preprocessing and frozen evaluation splits.
`,
  },
  {
    section_name: 'results',
    text: String.raw`
The proposed method improves prior work \cite{Smith2024} across internal and external cohorts.
External validation remains evidence locked and avoids unsupported deployment claims.
`,
  },
  {
    section_name: 'discussion',
    text: String.raw`
We compare the risk score $\mathrm{AUC}=0.91$ with calibrated confidence intervals.
This boilerplate sentence appears in two sections.
`,
  },
  {
    section_name: 'conclusion',
    text: String.raw`
This boilerplate sentence appears in two sections.
The final system emphasizes evidence-locked paper generation rather than broad clinical claims.
`,
  },
]

describe('pdfSectionMatch', () => {
  it('matches an exact rendered selection in one section', () => {
    const match = pdfMatchSection(
      'Digital pathology workflows increasingly use whole-slide images for clinical decision support.',
      sections,
    )
    expect(match?.section_name).toBe('introduction')
    expect(match?.confidence).toBeGreaterThan(0.95)
    expect(match?.ambiguous).toBe(false)
  })

  it('matches PDF numeric citations against LaTeX citation commands', () => {
    const match = pdfMatchSection(
      'The proposed method improves prior work [1] across internal and external cohorts.',
      sections,
    )
    expect(match?.section_name).toBe('results')
    expect(match?.confidence).toBeGreaterThan(0.9)
  })

  it('returns null when math-heavy rendered text cannot be matched confidently', () => {
    const match = pdfMatchSection('AUC equals zero point nine one plus other mathematical symbols', sections)
    expect(match).toBeNull()
  })

  it('matches cross-page selections after whitespace collapsing', () => {
    const match = pdfMatchSection(
      'Our contribution is an evidence-locked paper generation workspace\n\nfor reproducible reporting.',
      sections,
    )
    expect(match?.section_name).toBe('introduction')
    expect(match?.ambiguous).toBe(false)
  })

  it('matches PDF extraction with missing spaces and line-break hyphenation', () => {
    const match = pdfMatchSection(
      `Thispapermakesthreecautiouscontributions.First,itreportsaPHI-scrubbed
colorectal pathology patch-classification experiment with explicit dataset, split,
label, and validation artifacts. Second, it evaluates a constrained ResNet-50
feature-extraction pipeline with a linear classification component for the locked
benign and tumor classes. Third, it enforces evidence-bounded reporting: quan-
titative results are rendered only through approved metric placeholders and ta-
bles, and the absence of external validation is stated explicitly.`,
      [
        {
          section_name: 'introduction',
          text: `This paper makes three cautious contributions. First, it reports a PHI-scrubbed colorectal pathology patch-classification experiment with explicit dataset, split, label, and validation artifacts. Second, it evaluates a constrained ResNet-50 feature-extraction pipeline with a linear classification component for the locked benign and tumor classes. Third, it enforces evidence-bounded reporting: quantitative results are rendered only through approved metric placeholders and tables, and the absence of external validation is stated explicitly.`,
        },
        {
          section_name: 'methods',
          text: 'The model and training protocol are described here.',
        },
      ],
    )
    expect(match?.section_name).toBe('introduction')
    expect(match?.confidence).toBeGreaterThan(0.9)
  })

  it('rejects very short selections', () => {
    expect(pdfMatchSection('short text', sections)).toBeNull()
  })

  it("returns null when the selection doesn't appear in any section", () => {
    expect(
      pdfMatchSection('This unrelated sentence describes a completely different robotics benchmark.', sections),
    ).toBeNull()
  })

  it('marks boilerplate selections that fit multiple sections as ambiguous', () => {
    const match = pdfMatchSection('This boilerplate sentence appears in two sections.', sections)
    expect(match?.section_name).toBe('discussion')
    expect(match?.second_best?.section_name).toBe('conclusion')
    expect(match?.ambiguous).toBe(true)
  })

  it('matches source sections containing explicit cite/ref placeholders', () => {
    const match = pdfMatchSection('See [2] and Fig. 1 for the locked evidence flow.', [
      {
        section_name: 'methods',
        text: String.raw`See [CITE] and \ref{fig:flow} for the locked evidence flow.`,
      },
      {
        section_name: 'experiments',
        text: 'Evaluation protocol and dataset split details appear here.',
      },
    ])
    expect(match?.section_name).toBe('methods')
    expect(normalizeForMatch(String.raw`See [CITE] and \ref{fig:flow}`)).toContain('[cite]')
    expect(normalizeForMatch(String.raw`See [CITE] and \ref{fig:flow}`)).toContain('[ref]')
  })
})
