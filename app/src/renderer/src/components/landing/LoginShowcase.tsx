import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { ArrowUpRight } from 'lucide-react'
import pathlabLogo from '../../../public/images/pathlab-logo.png'
import { SpecimenStage } from './specimen/SpecimenStage'
import { StagePlayback } from './specimen/StagePlayback'

const WIDE = '(min-width: 1024px)'

/** The panel is hidden below 1024 px; don't start the 3D stage (or fetch its images) there. */
function useWideLayout() {
  const query = () => typeof window.matchMedia !== 'function' || window.matchMedia(WIDE).matches
  const [wide, setWide] = useState(query)
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const media = window.matchMedia(WIDE)
    const update = () => setWide(media.matches)
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])
  return wide
}

export function LoginShowcase() {
  const { t } = useTranslation()
  const wide = useWideLayout()
  if (!wide) return null
  return (
    <aside className="login-story">
      <SpecimenStage className="login-story__stage" />
      <Link to="/" className="login-story__brand" aria-label="PathLab"><img src={pathlabLogo} alt="PathLab" width="998" height="250" /></Link>
      <div className="login-story__body">
        <h2>{t('publicExperience.loginTitle')}</h2>
        <p className="login-story__description">{t('publicExperience.loginDescription')}</p>
      </div>
      <div className="login-story__footer"><a href="https://ko-fi.com/pathlab" target="_blank" rel="noopener noreferrer">{t('loginPage.supportMission')}<ArrowUpRight size={12} /></a><StagePlayback className="login-story__playback" /></div>
    </aside>
  )
}
