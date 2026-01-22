/**
 * PathLab Login Page
 *
 * Landing page with OAuth login integration to PathLab Server.
 */

import React from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { Microscope, Brain, Shield, Zap, LogIn, UserPlus, Loader2, FlaskConical } from 'lucide-react'
import { Button } from '../components/ui/button'

export default function LoginPage() {
  const navigate = useNavigate()
  const { login, signup, demoLogin, isLoading, error, isLoggedIn } = useAuth()
  const [showDisclaimer, setShowDisclaimer] = React.useState(false)

  // If already logged in, redirect to dashboard
  React.useEffect(() => {
    if (isLoggedIn) {
      navigate('/dashboard')
    }
  }, [isLoggedIn, navigate])

  const handleLogin = async () => {
    await login()
  }

  const handleSignup = async () => {
    await signup()
  }

  const handleDemoLoginClick = () => {
    setShowDisclaimer(true)
  }

  const handleDisclaimerAgree = () => {
    setShowDisclaimer(false)
    demoLogin()
    navigate('/dashboard')
  }

  const features = [
    {
      icon: Microscope,
      title: 'WSI Visualization',
      description: 'View and navigate multi-gigapixel whole slide images with smooth pan and zoom',
    },
    {
      icon: Brain,
      title: 'AI-Powered Analysis',
      description: 'Train and deploy deep learning models for pathology classification',
    },
    {
      icon: Shield,
      title: 'Privacy First',
      description: 'Your data never leaves your machine - models come to the data',
    },
    {
      icon: Zap,
      title: 'Smart Assistant',
      description: 'Describe your research in natural language, let AI set up the task',
    },
  ]

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-100 via-gray-100 to-slate-200 flex flex-col">
      {/* Header */}
      <header className="p-6">
        <img
          src="/images/pathlab-logo.png"
          alt="PathLab"
          className="h-16 w-auto"
        />
      </header>

      {/* Main Content */}
      <main className="flex-1 flex items-center justify-center px-6 py-12">
        <div className="max-w-6xl w-full grid lg:grid-cols-2 gap-12 items-center">
          {/* Left: Hero Content */}
          <div className="text-center lg:text-left">
            <h2 className="text-4xl lg:text-5xl font-bold text-slate-800 mb-6 leading-tight">
              Digital Pathology
              <br />
              <span className="bg-gradient-to-r from-blue-600 via-cyan-600 to-teal-600 bg-clip-text text-transparent">
                Powered by AI
              </span>
            </h2>
            <p className="text-lg text-slate-600 mb-8 leading-relaxed">
              PathLab is your local AI workstation for pathology research.
              Train models, analyze files, and generate insights - all while keeping your data private.
            </p>

            {/* CTA Buttons */}
            <div className="flex flex-col sm:flex-row gap-4 justify-center lg:justify-start">
              <Button
                onClick={handleDemoLoginClick}
                className="flex items-center justify-center gap-2 px-8 py-6 bg-gradient-to-r from-emerald-500 to-teal-600 text-white font-semibold rounded-xl shadow-lg hover:shadow-xl hover:scale-105 transition-all text-base"
              >
                <FlaskConical className="w-5 h-5" />
                Demo Login
              </Button>
              <Button
                onClick={handleLogin}
                disabled={isLoading}
                className="flex items-center justify-center gap-2 px-8 py-6 bg-gradient-to-r from-blue-500 to-cyan-600 text-white font-semibold rounded-xl shadow-lg hover:shadow-xl hover:scale-105 transition-all disabled:opacity-50 disabled:cursor-not-allowed text-base"
              >
                {isLoading ? (
                  <Loader2 className="w-5 h-5 animate-spin" />
                ) : (
                  <LogIn className="w-5 h-5" />
                )}
                Login with Server
              </Button>
            </div>

            {/* Secondary Actions */}
            <div className="mt-4 flex gap-4 justify-center lg:justify-start">
              <Button
                variant="secondary"
                onClick={handleSignup}
                disabled={isLoading}
                className="flex items-center justify-center gap-2 px-6 py-3 bg-slate-200 text-slate-700 font-medium rounded-lg border border-slate-300 hover:bg-slate-300 transition-all disabled:opacity-50 disabled:cursor-not-allowed text-sm"
              >
                <UserPlus className="w-4 h-4" />
                Create Account
              </Button>
            </div>

            {/* Error Message */}
            {error && (
              <div className="mt-4 p-4 bg-red-100 border border-red-300 rounded-lg text-red-600 text-sm">
                {error}
              </div>
            )}
          </div>

          {/* Right: Feature Cards */}
          <div className="grid grid-cols-2 gap-4">
            {features.map((feature) => {
              const Icon = feature.icon
              return (
                <div
                  key={feature.title}
                  className="p-6 bg-white backdrop-blur-sm rounded-2xl border border-slate-200 hover:bg-slate-50 transition-colors shadow-sm"
                >
                  <div className="w-12 h-12 bg-gradient-to-br from-blue-100 to-cyan-100 rounded-xl flex items-center justify-center mb-4">
                    <Icon className="w-6 h-6 text-blue-600" />
                  </div>
                  <h3 className="text-lg font-semibold text-slate-800 mb-2">{feature.title}</h3>
                  <p className="text-sm text-slate-500">{feature.description}</p>
                </div>
              )
            })}
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="p-6 text-center text-slate-500 text-sm">
        <p>© 2025 PathLab. Privacy-first AI for digital pathology.</p>
      </footer>

      {showDisclaimer && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4 animate-in fade-in duration-200">
          <div className="bg-white rounded-2xl shadow-2xl max-w-lg w-full overflow-hidden scale-100 animate-in zoom-in-95 duration-200">
            <div className="p-6 border-b border-gray-100 bg-gray-50/50">
              <h3 className="text-xl font-bold text-gray-900 flex items-center gap-2">
                <Shield className="w-5 h-5 text-blue-600" />
                User Agreement & Disclaimer
              </h3>
            </div>
            <div className="p-6 max-h-[60vh] overflow-y-auto text-slate-600 space-y-4 text-sm leading-relaxed scrollbar-thin scrollbar-thumb-gray-200 scrollbar-track-transparent">
              <p className="font-medium text-slate-900">Welcome to PathLab Research Demo.</p>
              <p>By continuing, you acknowledge and agree to the following conditions:</p>

              <div className="space-y-3 bg-slate-50 p-4 rounded-xl border border-slate-100">
                <div>
                    <h4 className="font-bold text-slate-900 mb-1 flex items-center gap-2">
                        <FlaskConical className="w-4 h-4 text-emerald-600" /> 1. Research Use Only
                    </h4>
                    <p>This software is strictly for research purposes. It is <strong>not approved</strong> for clinical diagnosis, patient care, or therapeutic decisions.</p>
                </div>

                <div>
                    <h4 className="font-bold text-slate-900 mb-1 flex items-center gap-2">
                        <Shield className="w-4 h-4 text-blue-600" /> 2. Data Privacy
                    </h4>
                    <p>This is a local-first application. While data primarily stays on your machine, you are solely responsible for ensuring compliance with privacy regulations (HIPAA, GDPR) for any data you process.</p>
                </div>

                <div>
                    <h4 className="font-bold text-slate-900 mb-1 flex items-center gap-2">
                         <Zap className="w-4 h-4 text-amber-500" /> 3. No Warranty
                    </h4>
                    <p>The software is provided "as is" without warranty of any kind. The authors are not liable for any issues arising from its use.</p>
                </div>
              </div>
            </div>
            <div className="p-6 bg-gray-50 flex justify-end gap-3 border-t border-gray-100">
              <Button
                variant="ghost"
                onClick={() => setShowDisclaimer(false)}
                className="text-slate-600 hover:text-slate-900 hover:bg-slate-200"
              >
                Cancel
              </Button>
              <Button
                onClick={handleDisclaimerAgree}
                className="bg-blue-600 hover:bg-blue-700 text-white shadow-md hover:shadow-lg transition-all"
              >
                I Agree & Continue
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

