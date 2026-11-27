import React, { useCallback, useEffect, useRef } from 'react'
import { MotionConfig } from 'framer-motion'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { InstallPWA } from '../components/InstallPWA'
import { LandingNavbar } from '../components/landing/LandingNavbar'
import { TrustStrip } from '../components/landing/TrustStrip'
import { FinalCTA } from '../components/landing/FinalCTA'
import { LandingFooter } from '../components/landing/LandingFooter'
import { HeroSection } from '../components/landing/HeroSection'
import { StickyWorkflowStory } from '../components/landing/StickyWorkflowStory'
import { CapabilityShowcase } from '../components/landing/CapabilityShowcase'
import { EvidenceLayer } from '../components/landing/EvidenceLayer'
import { SolutionsSection } from '../components/landing/SolutionsSection'
import { TrustDeploymentSection } from '../components/landing/TrustDeploymentSection'
import { PricingSection } from '../components/landing/PricingSection'
import { usePointerGlow } from '../components/landing/usePointerGlow'
import '../components/landing/public-experience.css'

export default function IntroductionPage() {
  const navigate = useNavigate()
  const { isLoggedIn } = useAuth()
  const { t } = useTranslation()
  const rootRef = useRef<HTMLDivElement>(null)
  usePointerGlow(rootRef)

  useEffect(() => {
    if (isLoggedIn) navigate('/dashboard')
  }, [isLoggedIn, navigate])

  const goToLogin = useCallback(() => navigate('/login'), [navigate])

  return (
    <MotionConfig reducedMotion="user">
    <div ref={rootRef} className="public-experience public-landing" data-public-page="landing">
      <a href="#main-content" className="public-skip-link">{t('publicExperience.skip')}</a>
      <LandingNavbar onLogin={goToLogin} />
      
      <main id="main-content" tabIndex={-1}>
        <HeroSection onPrimaryCta={goToLogin} />
        <TrustStrip />
        <StickyWorkflowStory />
        <CapabilityShowcase />
        <EvidenceLayer />
        <SolutionsSection />
        <TrustDeploymentSection />
        <PricingSection onPrimaryCta={goToLogin} />
        <FinalCTA onPrimaryCta={goToLogin} />
      </main>

      <LandingFooter />
      <InstallPWA />
    </div>
    </MotionConfig>
  )
}
