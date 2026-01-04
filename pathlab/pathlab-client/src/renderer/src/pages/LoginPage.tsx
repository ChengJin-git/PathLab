/**
 * PathLab Login Page
 *
 * Landing page with OAuth login integration to PathLab Server.
 */

import React from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { Microscope, Brain, Shield, Zap, LogIn, UserPlus, Loader2, FlaskConical } from 'lucide-react'

export default function LoginPage() {
  const navigate = useNavigate()
  const { login, signup, demoLogin, isLoading, error, isLoggedIn } = useAuth()

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

  const handleDemoLogin = () => {
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
              Train models, analyze slides, and generate insights - all while keeping your data private.
            </p>

            {/* CTA Buttons */}
            <div className="flex flex-col sm:flex-row gap-4 justify-center lg:justify-start">
              <button
                onClick={handleDemoLogin}
                className="flex items-center justify-center gap-2 px-8 py-4 bg-gradient-to-r from-emerald-500 to-teal-600 text-white font-semibold rounded-xl shadow-lg hover:shadow-xl hover:scale-105 transition-all"
              >
                <FlaskConical className="w-5 h-5" />
                Demo Login
              </button>
              <button
                onClick={handleLogin}
                disabled={isLoading}
                className="flex items-center justify-center gap-2 px-8 py-4 bg-gradient-to-r from-blue-500 to-cyan-600 text-white font-semibold rounded-xl shadow-lg hover:shadow-xl hover:scale-105 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isLoading ? (
                  <Loader2 className="w-5 h-5 animate-spin" />
                ) : (
                  <LogIn className="w-5 h-5" />
                )}
                Login with Server
              </button>
            </div>

            {/* Secondary Actions */}
            <div className="mt-4 flex gap-4 justify-center lg:justify-start">
              <button
                onClick={handleSignup}
                disabled={isLoading}
                className="flex items-center justify-center gap-2 px-6 py-3 bg-slate-200 text-slate-700 font-medium rounded-lg border border-slate-300 hover:bg-slate-300 transition-all disabled:opacity-50 disabled:cursor-not-allowed text-sm"
              >
                <UserPlus className="w-4 h-4" />
                Create Account
              </button>
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
    </div>
  )
}

