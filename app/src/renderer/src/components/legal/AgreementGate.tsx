import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../contexts/AuthContext'
import { DisclaimerModal } from '../DisclaimerModal'
import { PrivacyPolicyModal } from '../PrivacyPolicyModal'

/** Present terms before mounting any protected page, including the standalone viewer. */
export function AgreementGate() {
  const { acceptAgreement, logout, isLoading, error } = useAuth()
  const [showPrivacy, setShowPrivacy] = useState(false)
  const navigate = useNavigate()

  return (
    <div className="min-h-dvh bg-slate-50">
      <DisclaimerModal
        isOpen={!showPrivacy}
        isLoading={isLoading}
        error={error}
        onAccept={() => { void acceptAgreement() }}
        onDecline={async () => { await logout(); navigate('/', { replace: true }) }}
        onOpenPrivacyPolicy={() => setShowPrivacy(true)}
      />
      <PrivacyPolicyModal
        isOpen={showPrivacy}
        onClose={() => setShowPrivacy(false)}
        onBackToTerms={() => setShowPrivacy(false)}
      />
    </div>
  )
}
