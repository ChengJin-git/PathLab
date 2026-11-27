import { useTranslation } from 'react-i18next'
import { ArrowUpRight, Pause, Play } from 'lucide-react'
import { motion } from 'framer-motion'
import { Reveal } from './Reveal'
import { WorkflowPreview, type PreviewMode } from './WorkflowPreview'
import { usePreviewPlayback } from './usePreviewPlayback'

const modes: PreviewMode[] = ['viewer', 'research', 'results']

export function StickyWorkflowStory() {
  const { t } = useTranslation()
  const { ref, stage, playing, running, reducedMotion, progress, select, toggle } = usePreviewPlayback(3, 6200)
  return (
    <section id="workflow" className="public-section public-workflow">
      <div className="public-container">
        <Reveal className="public-section-heading">
          <p className="public-eyebrow">{t('publicExperience.workflowEyebrow')}</p>
          <h2>{t('publicExperience.workflowTitle')}</h2>
          <p>{t('publicExperience.workflowDescription')}</p>
        </Reveal>
        <div className="public-workflow__layout">
          <Reveal className="public-workflow__steps">
            {modes.map((value, index) => (
              <button type="button" key={value} aria-pressed={stage === index} onClick={() => select(index)} className={`public-workflow__step ${stage === index ? 'is-active' : ''}`}>
                <span className="public-workflow__number">0{index + 1}</span>
                <span><strong>{t(`publicExperience.workflow${index + 1}Title`)}</strong><span className="public-workflow__description">{t(`publicExperience.workflow${index + 1}Desc`)}</span></span>
                <ArrowUpRight size={18} />
                {stage === index && !reducedMotion && <motion.i className="demo-stage-progress" style={{ scaleX: progress }} aria-hidden="true" />}
              </button>
            ))}
          </Reveal>
          <div ref={ref} className="public-workflow__preview" data-playing={running}>
            <WorkflowPreview mode={modes[stage]} onModeChange={mode => select(modes.indexOf(mode))} running={running} reducedMotion={reducedMotion} />
            {!reducedMotion && <button type="button" className="workflow-playback" onClick={toggle} aria-pressed={playing}>
              {playing ? <Pause size={14} /> : <Play size={14} />}{t(playing ? 'publicExperience.agentPause' : 'publicExperience.agentPlay')}
            </button>}
          </div>
        </div>
      </div>
    </section>
  )
}
