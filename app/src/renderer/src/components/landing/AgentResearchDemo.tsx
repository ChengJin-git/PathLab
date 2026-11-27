import { useId } from 'react'
import { motion } from 'framer-motion'
import { useTranslation } from 'react-i18next'
import { Check, FlaskConical, Pause, Play, RotateCcw, Search } from 'lucide-react'
import { ResearchReportPreview } from './ResearchReportPreview'
import botAvatar from '../../../public/images/bot_avatar.png'
import { usePreviewPlayback } from './usePreviewPlayback'

const stages = ['agentPlan', 'agentExplore', 'agentReport'] as const

export function AgentResearchDemo() {
  const { t } = useTranslation()
  const { ref, stage, playing, running, reducedMotion, progress, select, toggle } = usePreviewPlayback(3, 5600)
  const panelId = useId()

  return (
    <div ref={ref} className="agent-research-demo" data-playing={running}>
      <div className="agent-research-demo__heading">
        <span className="agent-research-demo__identity"><img src={botAvatar} width="32" height="32" alt="" />{t('publicExperience.agentDemo')}</span>
        {!reducedMotion && <button type="button" onClick={toggle} aria-pressed={playing}>
          {playing ? <Pause size={14} /> : <Play size={14} />}
          {t(playing ? 'publicExperience.agentPause' : 'publicExperience.agentPlay')}
        </button>}
      </div>
      <div className="agent-research-demo__steps" role="group" aria-label={t('publicExperience.agentStages')}>
        {stages.map((key, index) => (
          <button key={key} type="button" onClick={() => select(index)} aria-pressed={stage === index} aria-controls={panelId}>
            <span aria-hidden="true">{index < stage ? <Check size={13} /> : index + 1}</span>{t(`publicExperience.${key}`)}
            {stage === index && !reducedMotion && <motion.i className="demo-stage-progress" style={{ scaleX: progress }} aria-hidden="true" />}
          </button>
        ))}
      </div>
      <div className="agent-research-demo__body" id={panelId} data-motion={reducedMotion ? 'reduced' : running ? 'playing' : 'paused'}>
        {stages.map((key, index) => (
          <motion.div
            key={key}
            className={`agent-research-demo__scene ${stage === index ? 'is-active' : ''}`}
            aria-hidden={stage !== index}
            initial={false}
            animate={{ opacity: stage === index ? 1 : 0, y: stage === index || reducedMotion ? 0 : 12 }}
            transition={{ duration: reducedMotion ? 0 : .35 }}
          >
            {index === 0 && <div className="agent-plan-preview">
              <p className="agent-plan-preview__question">{t('publicExperience.agentGoal')}</p>
              <div className="agent-plan-preview__context"><span>@ {t('publicExperience.collection')}</span><span>{t('publicExperience.agentGoalLabel')}</span></div>
              <ol>{[1, 2, 3].map(item => <li key={item} className="demo-build-item" style={{ animationDelay: `${item * .3}s` }}><span>0{item}</span>{t(`publicExperience.agentPlanItem${item}`)}<Check size={14} /></li>)}</ol>
            </div>}
            {index === 1 && <div className="agent-execution-preview">
              <h4>{t('publicExperience.agentExecution')}</h4>
              {[Search, FlaskConical, RotateCcw].map((Icon, index) => <div key={index} className="agent-execution-preview__row demo-build-item" style={{ animationDelay: `${index * .45}s` }}>
                <span className={`agent-execution-preview__icon ${index === 1 && stage === 1 && running ? 'is-running' : ''}`}><Icon size={18} strokeWidth={1.6} /></span>
                <div><strong>{t(`publicExperience.agentAction${index + 1}`)}</strong><p>{t(`publicExperience.agentAction${index + 1}Desc`)}</p></div>
                {index === 0 && <Check size={16} />}
              </div>)}
              <div className="agent-execution-preview__track" aria-hidden="true"><span /></div>
              <p className="agent-execution-preview__note">{t('publicExperience.agentControl')}</p>
            </div>}
            {index === 2 && <ResearchReportPreview compact animated />}
          </motion.div>
        ))}
      </div>
    </div>
  )
}
