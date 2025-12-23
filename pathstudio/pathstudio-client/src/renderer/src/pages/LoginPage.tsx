/**
 * PathStudio Login Page
 *
 * Landing page with OAuth login integration to PathStudio Server.
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
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-purple-900 to-slate-900 flex flex-col">
      {/* Header */}
      <header className="p-6">
        <div className="flex items-center space-x-3">
          <div className="w-12 h-12 bg-gradient-to-br from-blue-500 via-purple-500 to-pink-500 rounded-xl flex items-center justify-center shadow-lg">
            <span className="text-white text-xl font-bold">PS</span>
          </div>
          <div>
            <h1 className="text-2xl font-bold text-white">PathStudio</h1>
            <p className="text-sm text-gray-400">Pathology AI Platform</p>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="flex-1 flex items-center justify-center px-6 py-12">
        <div className="max-w-6xl w-full grid lg:grid-cols-2 gap-12 items-center">
          {/* Left: Hero Content */}
          <div className="text-center lg:text-left">
            <h2 className="text-4xl lg:text-5xl font-bold text-white mb-6 leading-tight">
              Digital Pathology
              <br />
              <span className="bg-gradient-to-r from-blue-400 via-purple-400 to-pink-400 bg-clip-text text-transparent">
                Powered by AI
              </span>
            </h2>
            <p className="text-lg text-gray-300 mb-8 leading-relaxed">
              PathStudio is your local AI workstation for pathology research.
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
                className="flex items-center justify-center gap-2 px-8 py-4 bg-gradient-to-r from-blue-500 to-purple-600 text-white font-semibold rounded-xl shadow-lg hover:shadow-xl hover:scale-105 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
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
                className="flex items-center justify-center gap-2 px-6 py-3 bg-white/10 text-white font-medium rounded-lg border border-white/20 hover:bg-white/20 transition-all disabled:opacity-50 disabled:cursor-not-allowed text-sm"
              >
                <UserPlus className="w-4 h-4" />
                Create Account
              </button>
            </div>

            {/* Error Message */}
            {error && (
              <div className="mt-4 p-4 bg-red-500/20 border border-red-500/50 rounded-lg text-red-300 text-sm">
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
                  className="p-6 bg-white/5 backdrop-blur-sm rounded-2xl border border-white/10 hover:bg-white/10 transition-colors"
                >
                  <div className="w-12 h-12 bg-gradient-to-br from-blue-500/20 to-purple-500/20 rounded-xl flex items-center justify-center mb-4">
                    <Icon className="w-6 h-6 text-purple-400" />
                  </div>
                  <h3 className="text-lg font-semibold text-white mb-2">{feature.title}</h3>
                  <p className="text-sm text-gray-400">{feature.description}</p>
                </div>
              )
            })}
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="p-6 text-center text-gray-500 text-sm">
        <p>© 2025 PathStudio. Privacy-first AI for digital pathology.</p>
      </footer>
    </div>
  )
}

