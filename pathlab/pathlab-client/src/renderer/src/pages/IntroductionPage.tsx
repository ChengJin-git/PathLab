import React, { useEffect } from 'react'
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

export default function IntroductionPage() {
  const navigate = useNavigate()
  const { isLoggedIn } = useAuth()

  useEffect(() => {
    if (isLoggedIn) navigate('/dashboard')
  }, [isLoggedIn, navigate])

  const goToLogin = () => navigate('/login')

  return (
    <div className="min-h-screen overflow-x-hidden bg-[color:var(--landing-page-bg)] text-[color:var(--landing-text-primary)]">
      <LandingNavbar onLogin={goToLogin} />
      
      <main className="pt-0">
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
  )
}
